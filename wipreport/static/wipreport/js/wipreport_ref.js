async function save(url){await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':''},body:JSON.stringify({rows:[]})});alert('저장 완료');}
document.querySelector('#btn-save-product').onclick=()=>save('/wip/api/ref/product-rules/save/');
document.querySelector('#btn-save-module').onclick=()=>save('/wip/api/ref/module-rules/save/');
document.querySelector('#btn-save-exclusion').onclick=()=>save('/wip/api/ref/exclusion-rules/save/');
document.querySelector('#btn-save-hot').onclick=()=>save('/wip/api/ref/hot-rules/save/');
