(() => {
  const phases=[
    ['校准本地运行环境','确认 Python 运行时与项目配置。','PYTHON RUNTIME'],
    ['开启记忆数据库','检查数据目录、迁移与持久化连接。','DATABASE / MIGRATIONS'],
    ['构建混合检索索引','装载向量、BM25 与图谱检索能力。','VECTOR + BM25 + GRAPH'],
    ['恢复记忆关联','重建相似、因果与共现连接。','HEBBIAN LINKS'],
    ['挂载上下文空间','载入 Context Space 与归类规则。','CONTEXT SPACE'],
    ['同步人格信号','恢复长期偏好与人格画像。','PERSONA SIGNALS'],
    ['启动后台同步','连接记忆监听与增量处理服务。','MEMO WATCHER'],
    ['等待管理平台接管','执行最终健康检查。','DASHBOARD READY']
  ];
  const started=Date.now(),steps=document.querySelector('#steps');
  steps.innerHTML=phases.map((p,i)=>`<div class="step" id="step-${i}"><i class="dot"></i><b>${p[0]}</b><em>${p[2]}</em></div>`).join('');
  function paint(progress,ready){const active=Math.min(phases.length-1,Math.floor(progress*(phases.length-1)));phases.forEach((_,i)=>document.querySelector(`#step-${i}`).className='step '+(ready||i<active?'done':i===active?'active':''));document.querySelector('#bar').style.width=`${Math.round(progress*100)}%`;document.querySelector('#phase').textContent=ready?'所有服务已经就绪':phases[active][0];document.querySelector('#detail').textContent=ready?'正在进入 Memo 管理平台。':phases[active][1];document.querySelector('#state').textContent=ready?'ALL SYSTEMS READY':'WAITING FOR SERVICES'}
  function timer(){const s=Math.floor((Date.now()-started)/1000);document.querySelector('#timer').textContent=`${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`}
  async function poll(){timer();const elapsed=(Date.now()-started)/1000;let ready=false;try{const r=await fetch('/boot-health',{cache:'no-store'});ready=!!(await r.json()).ready}catch{}paint(ready?1:Math.min(.93,.06+elapsed/24),ready);if(ready)setTimeout(()=>location.reload(),700);else setTimeout(poll,650)}
  poll();setInterval(timer,500);

  try{
    const canvas=document.querySelector('#view'),gl=canvas.getContext('webgl',{antialias:false,powerPreference:'high-performance'});if(!gl)throw Error('WebGL unavailable');
    const compile=(type,source)=>{const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s};
    const program=gl.createProgram();gl.attachShader(program,compile(gl.VERTEX_SHADER,VERT));gl.attachShader(program,compile(gl.FRAGMENT_SHADER,FRAG));gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));gl.useProgram(program);
    const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);const pos=gl.getAttribLocation(program,'a');gl.enableVertexAttribArray(pos);gl.vertexAttribPointer(pos,2,gl.FLOAT,false,0,0);
    const uniform=name=>gl.getUniformLocation(program,name),u={res:uniform('uRes'),time:uniform('uTime'),cam:uniform('uCam'),target:uniform('uTarget'),steps:uniform('uSteps'),din:uniform('uDin'),dout:uniform('uDout'),disk:uniform('uDisk'),stars:uniform('uStars'),rot:uniform('uRot'),debug:uniform('uDebug')};
    const radius=20.94,inclination=11.8*Math.PI/180,azimuth=10*Math.PI/180,cam=[radius*Math.cos(inclination)*Math.sin(azimuth),radius*Math.sin(inclination),radius*Math.cos(inclination)*Math.cos(azimuth)];
    function resize(){const d=Math.min(devicePixelRatio,1.5);canvas.width=innerWidth*d;canvas.height=innerHeight*d;gl.viewport(0,0,canvas.width,canvas.height)}addEventListener('resize',resize);resize();
    function frame(now){gl.uniform2f(u.res,canvas.width,canvas.height);gl.uniform1f(u.time,now/1000);gl.uniform3fv(u.cam,cam);gl.uniform3f(u.target,0,0,0);gl.uniform1f(u.steps,320);gl.uniform1f(u.din,2.75);gl.uniform1f(u.dout,40);gl.uniform1f(u.disk,1);gl.uniform1f(u.stars,1);gl.uniform1f(u.rot,1);gl.uniform1f(u.debug,0);gl.drawArrays(gl.TRIANGLES,0,6);requestAnimationFrame(frame)}requestAnimationFrame(frame);
  }catch(error){const out=document.querySelector('#render-error');out.style.display='block';out.textContent='Visual fallback active: '+error.message;}
})();
