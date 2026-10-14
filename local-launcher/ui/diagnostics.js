'use strict';
// 日志入口在加载、失败与维护页均可用，不依赖 WebUI 已成功启动。
(() => {
  const dialog=$('diagnostics-dialog'),output=$('diagnostics-output');
  let timer,lines='',summary='',reading=false;
  function append(value){lines=(lines+String(value||'')+'\n').slice(-100000);if(dialog.open&&!reading)output.textContent=lines;}
  function request(){if(bridge){reading=true;send({command:'diagnostics'});}else output.textContent=lines||'暂无启动记录。';}
  function open(){if(!dialog.open)dialog.showModal();$('diagnostics-summary').textContent=summary||'当前启动的实时记录；保存日志会导出诊断及相关日志文件。';output.textContent=lines||'正在读取…';request();clearInterval(timer);timer=setInterval(request,3000);}
  function fail(message){summary=String(message||'启动未完成，请查看详细日志。');append(summary);if(current==='start'){stopTips();document.body.classList.remove('handoff');progress.classList.add('finished','failed');$('progress-title').textContent='启动未完成';$('progress-message').textContent=displayMessage(summary);$('diagnostics-open').textContent='错误详情';$('return').classList.remove('hidden');setBusy(false);}}
  $('diagnostics-open').onclick=open;$('diagnostics-maintain').onclick=open;
  $('diagnostics-close').onclick=()=>dialog.close();dialog.addEventListener('close',()=>clearInterval(timer));
  $('diagnostics-save').onclick=()=>{$('diagnostics-status').textContent='选择保存位置…';send({command:'save-log'});};
  for(const id of ['start-browser','start-desktop'])$(id).addEventListener('click',()=>{lines='';summary='';progress.classList.remove('failed');$('diagnostics-open').textContent='查看启动日志';$('progress-stage').textContent='正在准备启动环境…';});
  document.addEventListener('keydown',event=>{if(dialog.open&&event.key==='Escape')event.stopImmediatePropagation();},true);
  if(bridge)bridge.addEventListener('message',({data})=>{
    if(data.kind==='event'){
      const r=data.record;if(r.action==='inspect')return;
      append(r.message);if(r.action==='start')$('progress-stage').textContent=displayMessage(r.message);
      if(['failed','cancelled'].includes(r.phase)||(r.phase==='complete'&&r.status!=='succeeded'))fail(r.message);
    }
    if(data.kind==='diagnostic-line')append(data.text);
    if(data.kind==='error')fail(data.message);
    if(data.kind==='diagnostics'){reading=false;output.textContent=data.text||lines;$('diagnostics-status').textContent='实时更新 · 文件尾部预览';}
    if(data.kind==='log-saved'){$('diagnostics-status').textContent=data.message;toast(data.message);}
  });
  window.addEventListener('unhandledrejection',event=>fail('界面处理异常：'+String(event.reason)));
})();
