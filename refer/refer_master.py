from .common import (
    FactsDashboardConfig,
    FactsDepartmentMaster,
    FactsDeptPermission,
    FactsEditHistory,
    FactsEvalStageMaster,
    FactsGuideDocument,
    FactsGuidePage,
    FactsLineMaster,
    FactsPreventRuleMaster,
    FactsVocAnswerStatusMaster,
    _check_page_permission,
    _ensure_browser_close_session,
    _get_actor,
    _popup_redirect,
    _record_access_history,
    login_required,
    redirect,
    render,
    services,
    static,
)

def _get_dept_master_map():
    return {str(row.id): row.department for row in FactsDepartmentMaster.objects.all().order_by("department", "id")}

def _resolve_department_from_post(raw_value, dept_map):
    raw = (raw_value or "").strip()
    if raw == "" or raw.upper() == "ALL":
        return "ALL"
    if raw in dept_map:
        return dept_map[raw]
    return raw if raw in dept_map.values() else "ALL"

@login_required
def master_view(request):
    _ensure_browser_close_session(request)
    permission_response = _check_page_permission(request, "master", require_edit=(request.method == "POST"))
    if permission_response is not None:
        return permission_response


    _record_access_history(request, 'master')

    actor = _get_actor(request)
    cfg = FactsDashboardConfig.objects.order_by("id").first()

    if request.method == "POST":
        action = request.POST.get("action", "").strip()

        if action == "save_dashboard_config":
            default_prp = request.POST.get("default_prp", "").strip() or "P1SD"
            inquiry_contact = request.POST.get("inquiry_contact", "").strip() or "minuk12.choi"

            if cfg:
                before_json = {
                    "default_prp": cfg.default_prp,
                    "inquiry_contact": cfg.inquiry_contact,
                }
                cfg.default_prp = default_prp
                cfg.inquiry_contact = inquiry_contact
                cfg.save()
            else:
                before_json = {}
                cfg = FactsDashboardConfig.objects.create(
                    default_prp=default_prp,
                    inquiry_contact=inquiry_contact,
                )

            FactsEditHistory.objects.create(
                action_type="dashboard_config_update",
                changed_by=actor,
                before_json=before_json,
                after_json={
                    "default_prp": cfg.default_prp,
                    "inquiry_contact": cfg.inquiry_contact,
                },
            )
            return redirect("facts:master")

        if action == "save_guide_paths":
            guide_title = (request.POST.get("guide_title") or "").strip() or "FACTS 사용 가이드"
            guide_total_pages_raw = (request.POST.get("guide_total_pages") or "").strip()

            try:
                guide_total_pages = int(guide_total_pages_raw)
            except ValueError:
                return _popup_redirect("총 페이지 수는 숫자로 입력하십시오.", "/facts/master/")

            if guide_total_pages < 1:
                return _popup_redirect("총 페이지 수는 1 이상이어야 합니다.", "/facts/master/")

            previous_guide = FactsGuideDocument.objects.filter(is_active=True).order_by("-updated_at", "-id").first()
            before_json = {}
            if previous_guide:
                before_json = {
                    "guide_id": previous_guide.id,
                    "title": previous_guide.title,
                    "page_count": previous_guide.pages.count(),
                }

            FactsGuideDocument.objects.filter(is_active=True).update(is_active=False)

            guide_doc = FactsGuideDocument.objects.create(
                title=guide_title,
                original_filename="STATIC_GUIDE",
                stored_ppt_path="",
                is_active=True,
            )

            for page_no in range(1, guide_total_pages + 1):
                static_path = static(f"facts/guide/page_{page_no:03d}.png")
                FactsGuidePage.objects.create(
                    guide=guide_doc,
                    page_no=page_no,
                    image_path=static_path,
                )

            FactsEditHistory.objects.create(
                action_type="guide_path_save",
                changed_by=actor,
                before_json=before_json,
                after_json={
                    "guide_id": guide_doc.id,
                    "title": guide_doc.title,
                    "page_count": guide_total_pages,
                    "path_rule": "/static/facts/guide/page_001.png 형식",
                },
            )
            return redirect("facts:master")

        if action == "upload_user_guide":
            return _popup_redirect(
                "이제 사용 가이드는 PPT 업로드가 아니라 정적 PNG 경로 방식으로 관리합니다.",
                "/facts/master/",
            )

        if action == "bulk_stage_save":
            total_rows = int(request.POST.get("total_rows", "0") or 0)
            staged_rows = []
            seen_codes = {}

            for i in range(total_rows):
                row_id = (request.POST.get(f"row_id_{i}") or "").strip()
                is_new = (request.POST.get(f"row_is_new_{i}") or "").strip() == "1"
                is_checked = (request.POST.get(f"row_checked_{i}") or "").strip() == "1"
                delete_flag = (request.POST.get(f"row_delete_flag_{i}") or "").strip() == "1"

                if delete_flag:
                    continue
                if not (is_new or is_checked):
                    continue

                stage_code = (request.POST.get(f"row_stage_code_{i}") or "").strip()
                stage_name = (request.POST.get(f"row_stage_name_{i}") or "").strip()
                sort_order_raw = (request.POST.get(f"row_sort_order_{i}") or "").strip()
                is_active_raw = (request.POST.get(f"row_is_active_{i}") or "1").strip()

                if not (stage_code and stage_name):
                    continue

                stage_code_key = stage_code.upper()
                if stage_code_key in seen_codes:
                    return _popup_redirect(f"{stage_code}값이 중복됩니다. 수정바랍니다.", "/facts/master/")
                seen_codes[stage_code_key] = True

                existing = FactsEvalStageMaster.objects.filter(stage_code=stage_code).first()
                if existing and str(existing.id) != row_id:
                    return _popup_redirect(f"{stage_code}값이 중복됩니다. 수정바랍니다.", "/facts/master/")

                staged_rows.append({
                    "row_id": row_id,
                    "is_new": is_new,
                    "is_checked": is_checked,
                    "stage_code": stage_code,
                    "stage_name": stage_name,
                    "sort_order": int(sort_order_raw) if sort_order_raw else 0,
                    "is_active": (is_active_raw == "1"),
                })

            for i in range(total_rows):
                row_id = (request.POST.get(f"row_id_{i}") or "").strip()
                is_checked = (request.POST.get(f"row_checked_{i}") or "").strip() == "1"
                delete_flag = (request.POST.get(f"row_delete_flag_{i}") or "").strip() == "1"

                if not row_id or not (delete_flag and is_checked):
                    continue

                obj = FactsEvalStageMaster.objects.filter(id=row_id).first()
                if not obj:
                    continue

                before_json = {
                    "id": obj.id,
                    "stage_code": obj.stage_code,
                    "stage_name": obj.stage_name,
                    "sort_order": obj.sort_order,
                    "is_active": obj.is_active,
                }
                obj.delete()

                FactsEditHistory.objects.create(
                    action_type="master_delete",
                    changed_by=actor,
                    before_json=before_json,
                    after_json={"deleted": True, "id": row_id},
                )

            for row in staged_rows:
                if row["is_new"]:
                    obj = FactsEvalStageMaster.objects.create(
                        stage_code=row["stage_code"],
                        stage_name=row["stage_name"],
                        sort_order=row["sort_order"],
                        is_active=row["is_active"],
                    )
                    FactsEditHistory.objects.create(
                        action_type="master_add",
                        changed_by=actor,
                        before_json={},
                        after_json={
                            "id": obj.id,
                            "stage_code": obj.stage_code,
                            "stage_name": obj.stage_name,
                            "sort_order": obj.sort_order,
                            "is_active": obj.is_active,
                        },
                    )
                else:
                    obj = FactsEvalStageMaster.objects.filter(id=row["row_id"]).first()
                    if not obj:
                        continue

                    before_json = {
                        "id": obj.id,
                        "stage_code": obj.stage_code,
                        "stage_name": obj.stage_name,
                        "sort_order": obj.sort_order,
                        "is_active": obj.is_active,
                    }

                    obj.stage_code = row["stage_code"]
                    obj.stage_name = row["stage_name"]
                    obj.sort_order = row["sort_order"]
                    obj.is_active = row["is_active"]
                    obj.save()

                    FactsEditHistory.objects.create(
                        action_type="master_update",
                        changed_by=actor,
                        before_json=before_json,
                        after_json={
                            "id": obj.id,
                            "stage_code": obj.stage_code,
                            "stage_name": obj.stage_name,
                            "sort_order": obj.sort_order,
                            "is_active": obj.is_active,
                        },
                    )
            return redirect("facts:master")

        if action == "bulk_line_save":
            total_rows = int(request.POST.get("line_total_rows", "0") or 0)
            staged_rows = []
            seen_line_ids = {}

            for i in range(total_rows):
                row_id = (request.POST.get(f"line_row_id_{i}") or "").strip()
                is_new = (request.POST.get(f"line_row_is_new_{i}") or "").strip() == "1"
                is_checked = (request.POST.get(f"line_row_checked_{i}") or "").strip() == "1"
                delete_flag = (request.POST.get(f"line_row_delete_flag_{i}") or "").strip() == "1"

                if delete_flag:
                    continue
                if not (is_new or is_checked):
                    continue

                line_id = (request.POST.get(f"line_row_line_id_{i}") or "").strip().upper()
                line_name = (request.POST.get(f"line_row_line_name_{i}") or "").strip()
                is_active_raw = (request.POST.get(f"line_row_is_active_{i}") or "1").strip()

                if not line_id:
                    continue

                if line_id in seen_line_ids:
                    return _popup_redirect(f"{line_id}값이 중복됩니다. 수정바랍니다.", "/facts/master/")
                seen_line_ids[line_id] = True

                existing = FactsLineMaster.objects.filter(line_id=line_id).first()
                if existing and str(existing.id) != row_id:
                    return _popup_redirect(f"{line_id}값이 중복됩니다. 수정바랍니다.", "/facts/master/")

                staged_rows.append({
                    "row_id": row_id,
                    "is_new": is_new,
                    "is_checked": is_checked,
                    "line_id": line_id,
                    "line_name": line_name,
                    "is_active": (is_active_raw == "1"),
                })

            for i in range(total_rows):
                row_id = (request.POST.get(f"line_row_id_{i}") or "").strip()
                is_checked = (request.POST.get(f"line_row_checked_{i}") or "").strip() == "1"
                delete_flag = (request.POST.get(f"line_row_delete_flag_{i}") or "").strip() == "1"

                if not row_id or not (delete_flag and is_checked):
                    continue

                obj = FactsLineMaster.objects.filter(id=row_id).first()
                if not obj:
                    continue

                before_json = {
                    "id": obj.id,
                    "line_id": obj.line_id,
                    "line_name": obj.line_name,
                    "is_active": obj.is_active,
                }
                obj.delete()

                FactsEditHistory.objects.create(
                    action_type="line_master_delete",
                    changed_by=actor,
                    before_json=before_json,
                    after_json={"deleted": True, "id": row_id},
                )

            for row in staged_rows:
                if row["is_new"]:
                    obj = FactsLineMaster.objects.create(
                        line_id=row["line_id"],
                        line_name=row["line_name"],
                        is_active=row["is_active"],
                    )
                    FactsEditHistory.objects.create(
                        action_type="line_master_add",
                        changed_by=actor,
                        before_json={},
                        after_json={
                            "id": obj.id,
                            "line_id": obj.line_id,
                            "line_name": obj.line_name,
                            "is_active": obj.is_active,
                        },
                    )
                else:
                    obj = FactsLineMaster.objects.filter(id=row["row_id"]).first()
                    if not obj:
                        continue

                    before_json = {
                        "id": obj.id,
                        "line_id": obj.line_id,
                        "line_name": obj.line_name,
                        "is_active": obj.is_active,
                    }

                    obj.line_id = row["line_id"]
                    obj.line_name = row["line_name"]
                    obj.is_active = row["is_active"]
                    obj.save()

                    FactsEditHistory.objects.create(
                        action_type="line_master_update",
                        changed_by=actor,
                        before_json=before_json,
                        after_json={
                            "id": obj.id,
                            "line_id": obj.line_id,
                            "line_name": obj.line_name,
                            "is_active": obj.is_active,
                        },
                    )
            return redirect("facts:master")

        if action == "bulk_voc_status_save":
            total_rows = int(request.POST.get("voc_status_total_rows", "0") or 0)
            staged_rows = []
            seen_names = {}
            for i in range(total_rows):
                row_id = (request.POST.get(f"voc_status_row_id_{i}") or "").strip()
                is_new = (request.POST.get(f"voc_status_row_is_new_{i}") or "").strip() == "1"
                is_checked = (request.POST.get(f"voc_status_row_checked_{i}") or "").strip() == "1"
                delete_flag = (request.POST.get(f"voc_status_row_delete_flag_{i}") or "").strip() == "1"
                if delete_flag:
                    continue
                if not (is_new or is_checked):
                    continue
                status_name = (request.POST.get(f"voc_status_row_name_{i}") or "").strip()
                sort_order = int((request.POST.get(f"voc_status_row_sort_order_{i}") or "0").strip() or 0)
                is_active = (request.POST.get(f"voc_status_row_is_active_{i}") or "1").strip() == "1"
                if not status_name:
                    continue
                key = status_name.upper()
                if key in seen_names:
                    return _popup_redirect(f"{status_name} 값이 중복됩니다.", "/facts/master/")
                seen_names[key] = True
                existing = FactsVocAnswerStatusMaster.objects.filter(status_name=status_name).first()
                if existing and str(existing.id) != row_id:
                    return _popup_redirect(f"{status_name} 값이 중복됩니다.", "/facts/master/")
                staged_rows.append({"row_id": row_id, "is_new": is_new, "status_name": status_name, "sort_order": sort_order, "is_active": is_active})

            for i in range(total_rows):
                row_id = (request.POST.get(f"voc_status_row_id_{i}") or "").strip()
                is_checked = (request.POST.get(f"voc_status_row_checked_{i}") or "").strip() == "1"
                delete_flag = (request.POST.get(f"voc_status_row_delete_flag_{i}") or "").strip() == "1"
                if row_id and is_checked and delete_flag:
                    obj = FactsVocAnswerStatusMaster.objects.filter(id=row_id).first()
                    if obj:
                        before_json = {"id": obj.id, "status_name": obj.status_name, "sort_order": obj.sort_order, "is_active": obj.is_active}
                        obj.is_active = False
                        obj.save(update_fields=["is_active", "updated_at"])
                        FactsEditHistory.objects.create(action_type="master_delete", changed_by=actor, before_json=before_json, after_json={"id": obj.id, "is_active": False})

            for row in staged_rows:
                if row["is_new"]:
                    obj = FactsVocAnswerStatusMaster.objects.create(status_name=row["status_name"], sort_order=row["sort_order"], is_active=row["is_active"])
                    FactsEditHistory.objects.create(action_type="master_add", changed_by=actor, before_json={}, after_json={"id": obj.id, "status_name": obj.status_name, "sort_order": obj.sort_order, "is_active": obj.is_active})
                else:
                    obj = FactsVocAnswerStatusMaster.objects.filter(id=row["row_id"]).first()
                    if not obj:
                        continue
                    before_json = {"id": obj.id, "status_name": obj.status_name, "sort_order": obj.sort_order, "is_active": obj.is_active}
                    obj.status_name = row["status_name"]
                    obj.sort_order = row["sort_order"]
                    obj.is_active = row["is_active"]
                    obj.save()
                    FactsEditHistory.objects.create(action_type="master_update", changed_by=actor, before_json=before_json, after_json={"id": obj.id, "status_name": obj.status_name, "sort_order": obj.sort_order, "is_active": obj.is_active})
            return redirect("facts:master")

        if action == "bulk_prevent_rule_save":
            total_rows = int(request.POST.get("prevent_total_rows", "0") or 0)
            staged_rows = []
            current_selected = None
            seen_days = set()
            for i in range(total_rows):
                row_id = (request.POST.get(f"prevent_row_id_{i}") or "").strip()
                is_new = (request.POST.get(f"prevent_row_is_new_{i}") or "").strip() == "1"
                is_checked = (request.POST.get(f"prevent_row_checked_{i}") or "").strip() == "1"
                delete_flag = (request.POST.get(f"prevent_row_delete_flag_{i}") or "").strip() == "1"
                if delete_flag:
                    continue
                days_raw = (request.POST.get(f"prevent_row_days_{i}") or "").strip()
                if not days_raw:
                    continue
                days = int(days_raw)
                if days in seen_days:
                    return _popup_redirect(f"PREVENT기준일 {days}일이 중복됩니다.", "/facts/master/")
                seen_days.add(days)
                is_current = (request.POST.get("prevent_current_row") or "") == str(i)
                if is_current:
                    current_selected = i
                color_code = (request.POST.get(f"prevent_row_color_{i}") or "#5B8FF9").strip() or "#5B8FF9"
                is_active = (request.POST.get(f"prevent_row_is_active_{i}") or "1") == "1"
                sort_order = int((request.POST.get(f"prevent_row_sort_order_{i}") or "0").strip() or 0)
                staged_rows.append({"row_id": row_id, "is_new": is_new, "is_checked": is_checked, "prevent_days": days, "color_code": color_code, "is_active": is_active, "sort_order": sort_order, "is_current": is_current})
            FactsPreventRuleMaster.objects.update(is_current=False)
            for i in range(total_rows):
                row_id = (request.POST.get(f"prevent_row_id_{i}") or "").strip()
                is_checked = (request.POST.get(f"prevent_row_checked_{i}") or "").strip() == "1"
                delete_flag = (request.POST.get(f"prevent_row_delete_flag_{i}") or "").strip() == "1"
                if row_id and is_checked and delete_flag:
                    obj = FactsPreventRuleMaster.objects.filter(id=row_id).first()
                    if obj:
                        before_json = {"id": obj.id, "prevent_days": obj.prevent_days, "color_code": obj.color_code, "is_active": obj.is_active, "is_current": obj.is_current}
                        obj.delete()
                        FactsEditHistory.objects.create(action_type="prevent_rule_delete", changed_by=actor, before_json=before_json, after_json={"deleted": True, "id": row_id})
            for row in staged_rows:
                if row["is_new"]:
                    obj = FactsPreventRuleMaster.objects.create(**{k: row[k] for k in ["sort_order", "prevent_days", "color_code", "is_active", "is_current"]})
                    FactsEditHistory.objects.create(action_type="prevent_rule_add", changed_by=actor, before_json={}, after_json={"id": obj.id, "prevent_days": obj.prevent_days, "color_code": obj.color_code, "is_active": obj.is_active, "is_current": obj.is_current})
                else:
                    obj = FactsPreventRuleMaster.objects.filter(id=row["row_id"]).first()
                    if not obj:
                        continue
                    before_json = {"id": obj.id, "prevent_days": obj.prevent_days, "color_code": obj.color_code, "is_active": obj.is_active, "is_current": obj.is_current}
                    obj.sort_order = row["sort_order"]
                    obj.prevent_days = row["prevent_days"]
                    obj.color_code = row["color_code"]
                    obj.is_active = row["is_active"]
                    obj.is_current = row["is_current"]
                    obj.save()
                    FactsEditHistory.objects.create(action_type="prevent_rule_update", changed_by=actor, before_json=before_json, after_json={"id": obj.id, "prevent_days": obj.prevent_days, "color_code": obj.color_code, "is_active": obj.is_active, "is_current": obj.is_current})
            if current_selected is None:
                first = FactsPreventRuleMaster.objects.filter(is_active=True).order_by("sort_order", "prevent_days", "id").first()
                if first:
                    FactsPreventRuleMaster.objects.exclude(id=first.id).update(is_current=False)
                    if not first.is_current:
                        first.is_current = True
                        first.save(update_fields=["is_current"])
            return redirect("facts:master")

        if action == "bulk_dept_permission_save":
            total_rows = int(request.POST.get("dept_total_rows", "0") or 0)
            dept_master_map = _get_dept_master_map()
            staged_rows = []
            for i in range(total_rows):
                row_id = (request.POST.get(f"dept_row_id_{i}") or "").strip()
                is_new = (request.POST.get(f"dept_row_is_new_{i}") or "").strip() == "1"
                is_checked = (request.POST.get(f"dept_row_checked_{i}") or "").strip() == "1"
                delete_flag = (request.POST.get(f"dept_row_delete_flag_{i}") or "").strip() == "1"
                if delete_flag:
                    continue
                if not (is_new or is_checked):
                    continue
                dept = _resolve_department_from_post(request.POST.get(f"dept_row_dept_{i}"), dept_master_map)
                username = (request.POST.get(f"dept_row_username_{i}") or "ALL").strip() or "ALL"
                can_view = (request.POST.get(f"dept_row_can_view_{i}") or "0") == "1"
                can_edit = (request.POST.get(f"dept_row_can_edit_{i}") or "0") == "1"
                if can_edit:
                    can_view = True
                if not can_view:
                    can_edit = False
                is_active = (request.POST.get(f"dept_row_is_active_{i}") or "0") == "1"
                page_values = request.POST.getlist(f"dept_row_page_values_{i}")
                page_permissions = {}
                for page_code in ["dashboard", "prevent_tip", "history", "voc", "master", "kpi"]:
                    page_view = (request.POST.get(f"dept_row_page_{page_code}_can_view_{i}") or "0") == "1"
                    page_edit = (request.POST.get(f"dept_row_page_{page_code}_can_edit_{i}") or "0") == "1"
                    if page_edit:
                        page_view = True
                    if not page_view:
                        page_edit = False
                    page_permissions[page_code] = {"can_view": page_view, "can_edit": page_edit}
                line_values = request.POST.getlist(f"dept_row_line_values_{i}")
                prp_values = request.POST.getlist(f"dept_row_prp_values_{i}")
                if "ALL" in page_values:
                    page_values = ["ALL"]
                if "ALL" in line_values:
                    line_values = ["ALL"]
                if "ALL" in prp_values:
                    prp_values = ["ALL"]
                page_values = sorted(set([p for p in page_values if p != "ALL"] + [p for p, perm in page_permissions.items() if perm.get("can_view")]))
                staged_rows.append({"row_id": row_id, "is_new": is_new, "can_view": can_view, "can_edit": can_edit, "is_active": is_active, "dept": dept, "username": username, "page_values": page_values or ["ALL"], "page_permissions": page_permissions, "line_values": sorted(set(line_values)), "prp_values": sorted(set(prp_values))})
            for i in range(total_rows):
                row_id = (request.POST.get(f"dept_row_id_{i}") or "").strip()
                is_checked = (request.POST.get(f"dept_row_checked_{i}") or "").strip() == "1"
                delete_flag = (request.POST.get(f"dept_row_delete_flag_{i}") or "").strip() == "1"
                if row_id and is_checked and delete_flag:
                    obj = FactsDeptPermission.objects.filter(id=row_id).first()
                    if obj:
                        before_json = {"id": obj.id, "dept": obj.dept, "username": getattr(obj, "username", "ALL"), "page_values": obj.page_values, "line_values": obj.line_values, "prp_values": obj.prp_values}
                        obj.delete()
                        FactsEditHistory.objects.create(action_type="dept_permission_delete", changed_by=actor, before_json=before_json, after_json={"deleted": True, "id": row_id})
            for row in staged_rows:
                if row["is_new"]:
                    obj = FactsDeptPermission.objects.create(**{k: row[k] for k in ["can_view", "can_edit", "is_active", "dept", "username", "page_values", "page_permissions", "line_values", "prp_values"]})
                    FactsEditHistory.objects.create(action_type="dept_permission_add", changed_by=actor, before_json={}, after_json={"id": obj.id, "dept": obj.dept, "username": obj.username, "page_values": obj.page_values, "line_values": obj.line_values, "prp_values": obj.prp_values})
                else:
                    obj = FactsDeptPermission.objects.filter(id=row["row_id"]).first()
                    if not obj:
                        continue
                    before_json = {"id": obj.id, "dept": obj.dept, "username": getattr(obj, "username", "ALL"), "page_values": obj.page_values, "line_values": obj.line_values, "prp_values": obj.prp_values}
                    obj.can_view = row["can_view"]
                    obj.can_edit = row["can_edit"]
                    obj.is_active = row["is_active"]
                    obj.dept = row["dept"]
                    obj.username = row["username"]
                    obj.page_values = row["page_values"]
                    obj.page_permissions = row["page_permissions"]
                    obj.line_values = row["line_values"]
                    obj.prp_values = row["prp_values"]
                    obj.save()
                    FactsEditHistory.objects.create(action_type="dept_permission_update", changed_by=actor, before_json=before_json, after_json={"id": obj.id, "dept": obj.dept, "username": obj.username, "page_values": obj.page_values, "line_values": obj.line_values, "prp_values": obj.prp_values})
            return redirect("facts:master")

    current_guide = FactsGuideDocument.objects.filter(is_active=True).order_by("-updated_at", "-id").first()
    current_guide_page_count = current_guide.pages.count() if current_guide else 0

    cfg2 = services.get_dashboard_config()
    inquiry_contact = cfg2.inquiry_contact if hasattr(cfg2, "inquiry_contact") else cfg2["inquiry_contact"]
    permission_options_raw = services.get_distinct_master_options(None)

    dept_permission_rows = list(FactsDeptPermission.objects.only("id", "can_view", "can_edit", "is_active", "dept", "username", "page_values", "page_permissions", "line_values", "prp_values").order_by("id"))
    for _row in dept_permission_rows:
        perms = getattr(_row, "page_permissions", {}) or {}
        normalized = {}
        for p in ["dashboard", "prevent_tip", "history", "voc", "master", "kpi"]:
            info = perms.get(p, {}) if isinstance(perms, dict) else {}
            can_view = bool(info.get("can_view")) if isinstance(info, dict) else (p in (_row.page_values or []))
            can_edit = bool(info.get("can_edit")) if isinstance(info, dict) else False
            if can_edit:
                can_view = True
            if not can_view:
                can_edit = False
            normalized[p] = {"can_view": can_view, "can_edit": can_edit}
        _row.page_permissions = normalized
    context = {
        "page_title": "기준정보",
        "eval_stages": FactsEvalStageMaster.objects.only("id", "stage_code", "stage_name", "sort_order", "is_active").order_by("sort_order", "stage_code"),
        "line_rows": FactsLineMaster.objects.only("id", "line_id", "line_name", "is_active").order_by("line_id"),
        "voc_answer_status_rows": FactsVocAnswerStatusMaster.objects.only("id", "status_name", "sort_order", "is_active").order_by("sort_order", "id"),
        "prevent_rule_rows": FactsPreventRuleMaster.objects.only("id", "sort_order", "prevent_days", "color_code", "is_active", "is_current").order_by("sort_order", "prevent_days", "id"),
        "dept_permission_rows": dept_permission_rows,
        "permission_page_options": ["ALL", "dashboard", "prevent_tip", "history", "voc", "master", "kpi"],
        "permission_source_options": {
            "dept_options": list(FactsDepartmentMaster.objects.all().order_by("department", "id")),
            "line_options": ["ALL"] + [x for x in permission_options_raw["line_options"] if x != "ALL"],
            "prp_options": ["ALL"] + [x for x in permission_options_raw["prp_options"] if x != "ALL"],
            "area_options": ["ALL"] + [x for x in permission_options_raw["area_options"] if x != "ALL"],
        },
        "dashboard_cfg": cfg,
        "current_guide": current_guide,
        "current_guide_page_count": current_guide_page_count,
        "inquiry_contact": inquiry_contact,
    }
    return render(request, "facts/master.html", context)
