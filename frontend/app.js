const DEFAULT_API = 'http://localhost:8000';
const state = {
  apiBase: localStorage.getItem('ironflow_api_base') || DEFAULT_API,
  token: localStorage.getItem('ironflow_token') || '',
  refreshToken: localStorage.getItem('ironflow_refresh_token') || '',
  user: readStoredJson('ironflow_user', null),
  authMode: 'login',
  currentPage: 'dashboard',
  sessions: [],
  activeSessionId: null,
  documents: [],
  chatMessages: {},
  pendingSources: [],
  chatStreams: createChatStreamRegistry(),
  chatDrafts: createChatDraftRegistry(),
  accountGeneration: 0,
  chatMessageRevision: {},
  chatHistoryLoadGeneration: {},
  pendingInitialChat: false,
  fitnessProfileOwner: null,
  fitnessProfile: null,
  fitnessProfileLoaded: false,
  fitnessProfilePromise: null,
  trainingPreview: null,
  trainingProfilePrefill: TrainingProfilePrefill.createTrainingProfilePrefillState(),
  activeWorkout: null,
  trainingRecords: [],
  currentTrainingPlan: null,
  nutritionEditingId: null,
  nutritionLoadedDate: null,
  nutritionRecords: [],
  nutritionLoadGeneration: 0,
  nutritionPhotoPreviewId: null,
  nutritionPhotoPreviewStatus: null,
  nutritionPhotoPreviewOwner: null,
  nutritionPhotoImageGeneration: 0,
  nutritionPhotoObjectUrl: null,
  admin: { allowed: false, isAdmin: false, isReviewer: false, roleCodes: [], tab: 'overview', usersPage: 1, reviewsPage: 1, reviewStatus: 'pending', userKeyword: '', roles: [], permissions: [], teams: [] },
};
let adminRolePopover = null;
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHtml = (value = '') => String(value).replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#039;','"':'&quot;'}[ch]));
const formatDate = value => { if (!value) return '—'; const d = new Date(value); return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit'}); };
const initials = value => String(value || 'U').trim().slice(0,1).toUpperCase();
function readStoredJson(key, fallback) { try { const value = localStorage.getItem(key); return value ? JSON.parse(value) : fallback; } catch { return fallback; } }
function apiUrl(path) { return `${state.apiBase.replace(/\/$/, '')}${path}`; }
function chatStorageKey() { const owner = state.user?.id ?? state.user?.username ?? 'guest'; return `ironflow_chat_messages_${owner}`; }
function profileStorageKey() { const owner = state.user?.id ?? state.user?.username ?? 'guest'; return `ironflow_profile_${encodeURIComponent(String(owner))}`; }
function profilePayload(profile = {}) {
  const numberOrNull = value => {
    if (value == null || String(value).trim() === '') return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : value;
  };
  return {
    height: numberOrNull(profile.height),
    weight: numberOrNull(profile.weight),
    age: numberOrNull(profile.age),
    sex: profile.sex || null,
    goal: profile.goal || null,
    experience: profile.experience || null,
    weekly_training_days: numberOrNull(profile.weekly_training_days),
    equipment: String(profile.equipment || '').trim() || null,
    limitations: String(profile.limitations || '').trim() || null,
  };
}
function syncFitnessProfile(force = false) {
  const owner = state.user?.id ?? state.user?.username;
  if (owner == null) return Promise.reject(new Error('登录后才能读取健身档案。'));
  const ownerKey = String(owner);
  if (state.fitnessProfileOwner !== ownerKey) {
    state.fitnessProfileOwner = ownerKey;
    state.fitnessProfile = null;
    state.fitnessProfileLoaded = false;
    state.fitnessProfilePromise = null;
  }
  if (state.fitnessProfilePromise) return state.fitnessProfilePromise;
  if (state.fitnessProfileLoaded && !force) return Promise.resolve(state.fitnessProfile);

  const loadAndMigrate = async () => {
    const saved = await request('/fitness/profile');
    const localKey = profileStorageKey();
    if (saved) {
      localStorage.removeItem(localKey);
      return saved;
    }

    // 只迁移旧版“按账号”缓存；全局键 ironflow_profile 不归属任何已验证账号，不自动导入。
    const legacy = readStoredJson(localKey, null);
    if (legacy && typeof legacy === 'object' && !Array.isArray(legacy)) {
      const migrated = await request('/fitness/profile', {
        method: 'PUT',
        body: JSON.stringify(profilePayload(legacy)),
      });
      localStorage.removeItem(localKey);
      return migrated;
    }
    return null;
  };

  let trackedPromise;
  trackedPromise = loadAndMigrate().then(profile => {
    if (String(state.user?.id ?? state.user?.username ?? '') === ownerKey) {
      state.fitnessProfile = profile;
      state.fitnessProfileLoaded = true;
    }
    return profile;
  }).finally(() => {
    if (state.fitnessProfilePromise === trackedPromise) state.fitnessProfilePromise = null;
  });
  state.fitnessProfilePromise = trackedPromise;
  return trackedPromise;
}
function resetFitnessProfileSync() {
  state.fitnessProfileOwner = null;
  state.fitnessProfile = null;
  state.fitnessProfileLoaded = false;
  state.fitnessProfilePromise = null;
}
function resetTrainingProfileForm() {
  const empty = TrainingProfilePrefill.resetTrainingProfilePrefillState(state.trainingProfilePrefill);
  $('#trainingEquipment').value = empty.equipment;
  $('#trainingDays').value = empty.trainingDays;
  $('#trainingLimitations').value = empty.limitations;
  $('#trainingRequest').value = '';
  $('#trainingGenerateButton').disabled = false;
  state.trainingPreview = null;
  state.currentTrainingPlan = null;
  $('#trainingGenerateStatus').textContent = '档案未填写的条件保持空白；可以手动填写。';
  $('#trainingPreview').innerHTML = '<div class="empty-state"><div><div class="empty-state-icon"><svg><use href="#i-dumbbell"/></svg></div><h3>还没有计划草稿</h3><p>填写训练要求后生成预览；生成过程不会保存计划。</p></div></div>';
  $('#trainingSavedPlans').innerHTML = '<div class="empty-loading">正在加载计划…</div>';
  $('#trainingWorkoutHistory').innerHTML = '<div class="empty-loading">正在加载训练记录…</div>';
}
function restoreChatMessages() { state.chatMessages = readStoredJson(chatStorageKey(), {}); if (!state.chatMessages || typeof state.chatMessages !== 'object' || Array.isArray(state.chatMessages)) state.chatMessages = {}; state.chatMessageRevision = {}; state.chatHistoryLoadGeneration = {}; }
function persistChatMessages() { if (!state.user) return; try { localStorage.setItem(chatStorageKey(), JSON.stringify(state.chatMessages)); } catch { toast('浏览器未能保存本机聊天记录。'); } }
function appendChatMessage(sessionId, message) { state.chatMessages[sessionId] ||= []; state.chatMessages[sessionId].push(message); state.chatMessageRevision[sessionId] = (state.chatMessageRevision[sessionId] || 0) + 1; persistChatMessages(); }
function saveActiveChatDraft() { state.chatDrafts.set(state.activeSessionId, $('#chatInput').value); }
function restoreChatDraft(sessionId) { const input=$('#chatInput'); input.value=state.chatDrafts.get(sessionId); input.style.height='auto'; input.style.height=`${Math.min(input.scrollHeight,115)}px`; }
function resetChatRuntime() {
  state.accountGeneration += 1;
  state.chatStreams.cancelAll();
  state.chatDrafts.clear();
  state.sessions = [];
  state.activeSessionId = null;
  state.chatMessages = {};
  state.chatMessageRevision = {};
  state.chatHistoryLoadGeneration = {};
  state.pendingSources = [];
  state.pendingInitialChat = false;
  resetTrainingProfileForm();
  state.nutritionLoadGeneration += 1;
  state.nutritionRecords = [];
  state.nutritionEditingId = null;
  state.nutritionLoadedDate = null;
  state.nutritionPhotoPreviewId = null;
  state.nutritionPhotoPreviewStatus = null;
  state.nutritionPhotoPreviewOwner = null;
  releaseNutritionPhotoImage();
  if ($('#nutritionPhotoResult')) $('#nutritionPhotoResult').innerHTML = '<p class="muted">选择图片后，识别结果会显示在这里供你核对。</p>';
  if ($('#nutritionPhotoStatus')) $('#nutritionPhotoStatus').textContent = '';
  if ($('#nutritionPhotoForm')) $('#nutritionPhotoForm').reset();
  if ($('#nutritionPhotoScan')) $('#nutritionPhotoScan').disabled = true;
  if ($('#nutritionForm')) resetNutritionForm();
  if ($('#nutritionSummary')) $('#nutritionSummary').innerHTML = '<div class="empty-loading">登录后加载每日营养汇总…</div>';
  if ($('#nutritionRecords')) $('#nutritionRecords').innerHTML = '<div class="empty-state compact"><div><h3>请登录后查看饮食记录</h3></div></div>';
  if ($('#nutritionRecordCount')) $('#nutritionRecordCount').textContent = '0 项';
}
function invalidateAuthentication() { state.token=''; state.refreshToken=''; state.user=null; resetFitnessProfileSync(); localStorage.removeItem('ironflow_token'); localStorage.removeItem('ironflow_refresh_token'); localStorage.removeItem('ironflow_user'); showAuth(); }
function timeoutSignal(milliseconds) { if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') return AbortSignal.timeout(milliseconds); const controller = new AbortController(); window.setTimeout(() => controller.abort(), milliseconds); return controller.signal; }
function authHeaders(extra = {}) { return state.token ? {...extra, Authorization: `Bearer ${state.token}`} : extra; }
function toast(message) { const node = $('#toast'); node.textContent = message; node.classList.add('visible'); clearTimeout(toast.timer); toast.timer = setTimeout(() => node.classList.remove('visible'), 3200); }
function showError(error) { const message = error?.message || '请求失败，请检查后端服务。'; toast(message); }
function parseError(data, fallback = '请求失败') { return data?.detail || data?.message || data?.error || fallback; }
async function request(path, options = {}) {
  const response = await fetch(apiUrl(path), { ...options, headers: authHeaders({'Content-Type':'application/json', ...(options.headers || {})}) });
  let data = null; try { data = await response.json(); } catch { data = null; }
  if (response.status === 401) { const wasAuthenticated = Boolean(state.user || state.token); invalidateAuthentication(); if (wasAuthenticated) toast('登录已过期，请重新登录。'); throw new Error('登录已过期'); }
  if (!response.ok) throw new Error(parseError(data, `请求失败（${response.status}）`));
  return data;
}
function showAuth() { resetChatRuntime(); state.admin.allowed=false; state.admin.isAdmin=false; state.admin.isReviewer=false; state.admin.roleCodes=[]; $('.nav-item-admin')?.classList.add('hidden'); $('#authScreen').classList.remove('hidden'); $('#appShell').classList.add('hidden'); }
function showApp() { $('#authScreen').classList.add('hidden'); $('#appShell').classList.remove('hidden'); updateUserUI(); navigate(state.currentPage || 'dashboard', false); checkApi(); updateAdminNavigation(); syncFitnessProfile().catch(error => console.warn('健身档案同步失败；打开档案页后可重试。', error)); }
function updateUserUI() {
  const user = state.user || {}; const name = user.username || '训练者';
  $('#topUsername').textContent = name; $('#userAvatar').textContent = initials(name); $('#profileName').textContent = name; $('#profileEmail').textContent = user.email || '未设置邮箱'; $('#profilePortrait').textContent = initials(name); $('#profileId').textContent = user.id ?? '—'; $('#profileJoined').textContent = formatDate(user.create_at); $('#profileApiUrl').textContent = state.apiBase;
}
function updateAuthCopy() {
  const register = state.authMode === 'register'; $('#authEyebrow').textContent = register ? 'START YOUR FLOW' : 'WELCOME BACK'; $('#authTitle').textContent = register ? '为自己开一个训练空间。' : '回来继续练。'; $('#authSubtitle').textContent = register ? '注册后，开始把训练知识和每一次进步收进来。' : '登录你的训练空间，让今天的努力有迹可循。'; $('#authSubmit').innerHTML = register ? '创建账号并开始 <svg><use href="#i-arrow"/></svg>' : '登录并开始 <svg><use href="#i-arrow"/></svg>'; $('#authSwitchText').textContent = register ? '已经有账号？' : '还没有账号？'; $('#authSwitch').textContent = register ? '返回登录' : '创建一个'; $('#emailField').classList.toggle('is-visible', register); $('#email').required = register; $('#password').autocomplete = register ? 'new-password' : 'current-password'; $('#authError').textContent = ''; }
async function submitAuth(event) {
  event.preventDefault(); const form = event.currentTarget; const button = $('#authSubmit'); const data = Object.fromEntries(new FormData(form).entries()); $('#authError').textContent = ''; button.disabled = true;
  try { const endpoint = state.authMode === 'register' ? '/user/register' : '/user/login'; if (state.authMode === 'register') await request(endpoint,{method:'POST',body:JSON.stringify({username:data.username,password:data.password,email:data.email})}); const result = state.authMode === 'register' ? await request('/user/login',{method:'POST',body:JSON.stringify({username:data.username,password:data.password})}) : await request(endpoint,{method:'POST',body:JSON.stringify({username:data.username,password:data.password})}); resetChatRuntime(); state.token=result.token; state.refreshToken=result.refresh_token || ''; state.user=result.user || {username:data.username}; restoreChatMessages(); localStorage.setItem('ironflow_token',state.token); localStorage.setItem('ironflow_refresh_token',state.refreshToken); localStorage.setItem('ironflow_user',JSON.stringify(state.user)); showApp(); toast(state.authMode === 'register' ? '账号创建好了，今天开始你的训练流程。' : '欢迎回来，今天也练得有方向。'); }
  catch (error) { $('#authError').textContent = error.message; } finally { button.disabled = false; }
}
function navigate(page, updateHash = true) { const valid = ['dashboard','coach','training','nutrition','library','profile','admin']; if (!valid.includes(page)) page='dashboard'; state.currentPage=page; if (updateHash) history.replaceState(null,'',`#${page}`); $$('.nav-item').forEach(item => item.classList.toggle('active',item.dataset.page===page)); $$('.page').forEach(node => node.classList.toggle('active',node.id===`page-${page}`)); const titles={dashboard:'今日训练',coach:'AI 教练',training:'训练计划',nutrition:'营养记录',library:'健身知识库',profile:'我的档案',admin:'管理台'}; $('#pageTitle').textContent=titles[page]; closeMobileMenu(); if (page==='dashboard') loadDashboard(); if (page==='coach') loadSessions(); if (page==='training') loadTrainingPlans(); if (page==='nutrition') loadNutritionDay(); if (page==='library') loadDocuments(); if (page==='profile') loadProfile(); if (page==='admin') loadAdmin(); }
function closeMobileMenu() { $('#sidebar').classList.remove('open'); $('#mobileOverlay').classList.remove('visible'); }
function toggleMobileMenu() { $('#sidebar').classList.toggle('open'); $('#mobileOverlay').classList.toggle('visible'); }
async function checkApi() { const indicator=$('#apiIndicator'); try { const response=await fetch(apiUrl('/docs'),{signal:AbortSignal.timeout(2800)}); if (!response.ok) throw new Error(); indicator.classList.remove('offline'); indicator.querySelector('span:last-child').textContent='后端已连接'; $('#profileConnectionStatus').classList.remove('is-offline'); $('#profileConnectionStatus').innerHTML='<i></i>已连接'; } catch { indicator.classList.add('offline'); indicator.querySelector('span:last-child').textContent='连接异常'; $('#profileConnectionStatus').classList.add('is-offline'); $('#profileConnectionStatus').innerHTML='<i></i>无法连接'; } }
async function loadDashboard() {
  const statsGrid = $('#trainingStatsGrid');
  const recentBox = $('#dashboardWorkoutHistory');
  if (statsGrid) statsGrid.innerHTML = '<div class="empty-loading">正在加载训练统计…</div>';
  if (recentBox) recentBox.innerHTML = '<div class="empty-loading">正在加载训练记录…</div>';
  try {
    const [stats, sessions, docs] = await Promise.all([request('/user/stats'), request('/chat/session'), request('/pg/check_all')]);
    $('#docCount').textContent = stats?.document_count ?? docs?.length ?? '0';
    $('#sessionCount').textContent = sessions?.length ?? '0';
    $('#libraryCount').textContent = docs?.length ?? '0';
    $('#sessionListCount').textContent = sessions?.length ?? '0';
  } catch { $('#docCount').textContent='—'; $('#sessionCount').textContent='—'; }
  try {
    const {stats: trainingStats, workouts} = await TrainingWorkoutUI.fetchDashboardTrainingData(request);
    if (statsGrid) statsGrid.innerHTML = TrainingWorkoutUI.renderStats(trainingStats);
    if (recentBox) recentBox.innerHTML = TrainingWorkoutUI.renderHistory(workouts, {compact: true});
  } catch (error) {
    if (statsGrid) statsGrid.innerHTML = TrainingWorkoutUI.renderStats(null);
    if (recentBox) recentBox.innerHTML = `<div class="empty-state compact"><h3>训练数据暂不可用</h3><p>${escapeHtml(error.message)}</p></div>`;
  }
}
function renderSessions() { const list=$('#sessionList'); $('#sessionListCount').textContent=state.sessions.length; if (!state.sessions.length) { list.innerHTML='<div class="session-empty">还没有对话。<br>从一个训练问题开始。</div>'; return; } list.innerHTML=state.sessions.map(session=>{const stream=state.chatStreams.get(session.id);const streaming=stream?.status==='streaming';const failed=stream?.status==='failed';return `<div class="session-item ${session.id===state.activeSessionId?'active':''} ${streaming?'is-generating':''}" data-session-id="${session.id}"><svg><use href="#i-chat"/></svg><span class="session-item-title">${escapeHtml(session.title)}</span>${streaming?'<span class="session-stream-status" role="status">正在回答</span>':failed?'<span class="session-stream-status is-failed" role="status">回答中断</span>':''}<button class="session-delete" data-delete-session="${session.id}" aria-label="删除会话" ${streaming?'disabled title="回答完成后才能删除"':''}><svg><use href="#i-close"/></svg></button></div>`;}).join(''); }
async function loadSessionMessages(id) {
  const accountGeneration=state.accountGeneration;
  const loadGeneration=(state.chatHistoryLoadGeneration[id]||0)+1;
  const messageRevision=state.chatMessageRevision[id]||0;
  const previousMessages=(state.chatMessages[id]||[]).slice();
  const ownerKey=String(state.user?.id??state.user?.username??'');
  state.chatHistoryLoadGeneration[id]=loadGeneration;
  const messages=await request(`/chat/session/${id}/messages?limit=40`);
  if(accountGeneration!==state.accountGeneration||state.chatHistoryLoadGeneration[id]!==loadGeneration||!state.sessions.some(session=>String(session.id)===String(id)))return;
  const loaded=messages.map(message=>({type:message.role,text:message.content,time:message.create_at,sources:message.sources||[]}));
  state.chatStreams.recoverInterrupted(id,loaded,{accountGeneration,ownerKey});
  const stream=state.chatStreams.get(id);
  const appendIfMissing=message=>{if(!message)return;const last=loaded[loaded.length-1];if(last?.type===message.type&&last.text===message.text)return;loaded.push(message);};
  const streamReplyPersisted=stream?.status==='succeeded'&&stream.assistantMessage&&loaded.at(-1)?.type==='assistant'&&loaded.at(-1)?.text===stream.assistantMessage.text;
  if((stream?.status==='streaming'||stream?.status==='failed'||stream?.status==='succeeded')&&!streamReplyPersisted)appendIfMissing(stream.userMessage);
  if((state.chatMessageRevision[id]||0)!==messageRevision){
    const localTail=(state.chatMessages[id]||[]).slice(previousMessages.length);
    localTail.forEach(appendIfMissing);
  }
  if((stream?.status==='streaming'||stream?.status==='failed'||stream?.status==='succeeded')&&!streamReplyPersisted)appendIfMissing(stream.assistantMessage);
  state.chatMessages[id]=loaded;
  if(state.activeSessionId===id){persistChatMessages();renderChat(id);}
}
async function loadSessions() { saveActiveChatDraft(); const accountGeneration=state.accountGeneration; try { const sessions=await request('/chat/session'); if(accountGeneration!==state.accountGeneration)return; state.sessions=sessions; if(!state.sessions.some(x=>x.id===state.activeSessionId)) state.activeSessionId=state.sessions[0]?.id||null; restoreChatDraft(state.activeSessionId); renderSessions(); if (state.activeSessionId) { await loadSessionMessages(state.activeSessionId); } else { renderWelcome(); } } catch (error) { if(accountGeneration===state.accountGeneration)$('#sessionList').innerHTML='<div class="session-empty">会话列表暂时不可用。</div>'; } }
async function createSession(title='新的训练咨询') { saveActiveChatDraft(); const previousSessionId=state.activeSessionId; const accountGeneration=state.accountGeneration; try { const session=await request('/chat/session',{method:'POST',body:JSON.stringify({title})}); if(accountGeneration!==state.accountGeneration)return null; if(previousSessionId==null)state.chatDrafts.move(null,session.id); else state.chatDrafts.set(session.id,''); state.sessions=[session,...state.sessions.filter(x=>x.id!==session.id)]; state.activeSessionId=session.id; state.chatMessages[session.id]=[]; state.chatMessageRevision[session.id]=0; restoreChatDraft(session.id); renderSessions(); persistChatMessages(); renderChat(session.id); return session; } catch(error){ if(accountGeneration===state.accountGeneration)showError(error); return null; } }
async function nameSessionFromFirstQuestion(sessionId, query) {
  const accountGeneration=state.accountGeneration;
  const title = Array.from(query.trim()).slice(0, 32).join('');
  if (!title) return;
  try {
    const session = await request(`/chat/session/${sessionId}`, {method:'PUT', body:JSON.stringify({title})});
    if(accountGeneration!==state.accountGeneration||!state.sessions.some(item=>String(item.id)===String(sessionId)))return;
    state.sessions = state.sessions.map(item => item.id === sessionId ? session : item);
    renderSessions();
  } catch (error) {
    if(accountGeneration===state.accountGeneration)showError(error);
  }
}
async function deleteSession(id) { if(state.chatStreams.isStreaming(id)){toast('该对话正在回答，完成后才能删除。');return;} const accountGeneration=state.accountGeneration; try { await request(`/chat/session/${id}`,{method:'DELETE'}); if(accountGeneration!==state.accountGeneration)return; state.chatStreams.delete(id); state.chatDrafts.delete(id); delete state.chatMessages[id]; delete state.chatMessageRevision[id]; delete state.chatHistoryLoadGeneration[id]; persistChatMessages(); state.sessions=state.sessions.filter(s=>String(s.id)!==String(id)); if (String(state.activeSessionId)===String(id)) { state.activeSessionId=state.sessions[0]?.id || null; restoreChatDraft(state.activeSessionId); if (state.activeSessionId) renderChat(state.activeSessionId); else renderWelcome(); } renderSessions(); } catch(error){if(accountGeneration===state.accountGeneration)showError(error);} }
function renderWelcome() { $('#sourceTray').classList.add('hidden'); const box=$('#chatMessages'); box.classList.add('is-welcome'); box.innerHTML='<div class="coach-welcome"><span class="welcome-spark"><svg><use href="#i-spark"/></svg></span><p class="eyebrow">LET\'S GET STRONGER</p><h2>今天，想解决<br>哪个训练难题？</h2><p>可以问我动作、计划、饮食或恢复。越具体，我越能给你有用的建议。</p><div class="prompt-chips"><button data-prompt="新手一周练几次比较合适？">新手一周练几次？</button><button data-prompt="深蹲主要锻炼哪些肌群？">深蹲练哪些肌群？</button><button data-prompt="减脂期怎么安排训练和饮食？">减脂怎么安排训练？</button><button data-prompt="力量训练后如何安排恢复？">训练后怎么恢复？</button></div></div>'; updateChatComposerState(); }
function renderChat(id) { state.activeSessionId=id; const messages=state.chatMessages[id]||[]; const stream=state.chatStreams.get(id); const box=$('#chatMessages'); if(!messages.length&&!stream){renderWelcome();updateChatComposerState();return;} box.classList.remove('is-welcome'); box.innerHTML=messages.map(message=>message.type==='user'?messageHtml(message,true):messageHtml(message,false)).join(''); if(stream?.status==='streaming'||stream?.status==='failed'){box.insertAdjacentHTML('beforeend',streamMessageHtml(stream));} const lastAssistant=[...messages].reverse().find(message=>message.type==='assistant'); renderSources((stream?.status==='streaming'||stream?.status==='failed')?stream.sources:(lastAssistant?.sources||[])); box.scrollTop=box.scrollHeight; updateChatComposerState(); }
function streamMessageHtml(stream) { const text=stream.answer?escapeHtml(stream.answer):'<span class="typing-dots"><i></i><i></i><i></i></span>'; const streamingClass=stream.answer?' is-streaming':''; const status=stream.status==='failed'?`AI 教练 · 回答中断：${escapeHtml(stream.error||'请求失败')}`:'AI 教练 · 正在回答'; return `<div class="chat-row" data-stream-session="${escapeHtml(stream.sessionId)}"><div class="message-avatar"><svg><use href="#i-mark"/></svg></div><div class="message-content"><div class="message-bubble${streamingClass}">${text}</div><div class="message-meta">${status}</div></div></div>`; }
function updateStreamMessageNode(stream) {
  if(state.activeSessionId!==stream.sessionId)return false;
  const box=$('#chatMessages');
  box.classList.remove('is-welcome');
  const statusText=stream.status==='failed'?`AI 教练 · 回答中断：${stream.error||'请求失败'}`:'AI 教练 · 正在回答';
  return patchChatStreamMessage(box,stream.sessionId,stream.answer,statusText);
}
function updateChatComposerState() { const stream=state.chatStreams.get(state.activeSessionId); const streaming=stream?.status==='streaming'; const button=$('#sendButton'); if(button)button.disabled=Boolean(streaming); const note=$('.composer-bottom span'); if(note)note.textContent=streaming?'本对话正在回答；可以切换其他对话继续提问。':'消息会保存到当前会话；AI 会参考本次会话历史，建议仅供参考。'; }
function renderActiveStream(sessionId, updateSessionList=false, updateSources=false) { if(state.activeSessionId===sessionId){const stream=state.chatStreams.get(sessionId); if(stream?.status==='streaming'||stream?.status==='failed'){if(!updateStreamMessageNode(stream))renderChat(sessionId); else if(updateSources)renderSources(stream.sources);} else renderChat(sessionId);} if(updateSessionList)renderSessions(); }
const MARKDOWN_BREAK = '\uE000';
function markdownInline(value) {
  const codeSpans = [];
  let html = escapeHtml(value).replace(/`([^`\n]+)`/g, (_, code) => {
    const token = `\uE100${codeSpans.length}\uE101`;
    codeSpans.push(`<code>${code}</code>`);
    return token;
  });
  html = html
    .replace(/\*\*([^*\n]+?)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>')
    .replaceAll(MARKDOWN_BREAK, '<br>');
  codeSpans.forEach((code, index) => { html = html.replaceAll(`\uE100${index}\uE101`, code); });
  return html;
}
function splitMarkdownTableRow(line) {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim());
}
function isMarkdownTableSeparator(line) {
  const cells = splitMarkdownTableRow(line);
  return cells.length > 1 && cells.every(cell => /^:?-{3,}:?$/.test(cell));
}
function isMarkdownBlockStart(lines, index) {
  const line = lines[index] || '';
  return /^\s{0,3}#{1,6}\s+/.test(line)
    || /^\s{0,3}(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})\s*$/.test(line)
    || /^\s{0,3}>\s?/.test(line)
    || /^\s*(?:[-+*]\s+|\d+[.)]\s+)/.test(line)
    || (index + 1 < lines.length && line.includes('|') && isMarkdownTableSeparator(lines[index + 1]));
}
function renderMarkdown(value = '') {
  const source = String(value || '')
    .replace(/\r\n?/g, '\n')
    .replace(/\\?<br\s*\/?>/gi, MARKDOWN_BREAK)
    .replace(/\\([*_`#|])/g, '$1')
    .trim();
  if (!source) return '';
  const lines = source.split('\n');
  const blocks = [];
  let paragraph = [];
  const flushParagraph = () => {
    if (paragraph.length) blocks.push(`<p>${paragraph.map(markdownInline).join('<br>')}</p>`);
    paragraph = [];
  };

  for (let index = 0; index < lines.length;) {
    const line = lines[index];
    if (!line.trim()) { flushParagraph(); index += 1; continue; }

    const tableSeparator = index + 1 < lines.length && line.includes('|') && isMarkdownTableSeparator(lines[index + 1]);
    if (tableSeparator) {
      flushParagraph();
      const headers = splitMarkdownTableRow(line);
      const rows = [];
      let rowIndex = index + 2;
      while (rowIndex < lines.length && lines[rowIndex].trim() && lines[rowIndex].includes('|')) {
        rows.push(splitMarkdownTableRow(lines[rowIndex]));
        rowIndex += 1;
      }
      const headerHtml = headers.map(cell => `<th>${markdownInline(cell)}</th>`).join('');
      const rowsHtml = rows.map(row => `<tr>${headers.map((_, cellIndex) => `<td>${markdownInline(row[cellIndex] || '')}</td>`).join('')}</tr>`).join('');
      blocks.push(`<div class="markdown-table-wrap"><table><thead><tr>${headerHtml}</tr></thead><tbody>${rowsHtml}</tbody></table></div>`);
      index = rowIndex;
      continue;
    }

    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (heading) {
      flushParagraph();
      const level = Math.min(heading[1].length + 1, 6);
      blocks.push(`<h${level}>${markdownInline(heading[2])}</h${level}>`);
      index += 1;
      continue;
    }
    if (/^\s{0,3}(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})\s*$/.test(line)) {
      flushParagraph();
      blocks.push('<hr>');
      index += 1;
      continue;
    }
    if (/^\s{0,3}>\s?/.test(line)) {
      flushParagraph();
      const quote = [];
      while (index < lines.length && /^\s{0,3}>\s?/.test(lines[index])) {
        quote.push(lines[index].replace(/^\s{0,3}>\s?/, ''));
        index += 1;
      }
      blocks.push(`<blockquote>${quote.map(markdownInline).join('<br>')}</blockquote>`);
      continue;
    }

    const listItem = line.match(/^\s*(?:([-+*])\s+|(\d+)[.)]\s+)(.*)$/);
    if (listItem) {
      flushParagraph();
      const ordered = Boolean(listItem[2]);
      const items = [];
      while (index < lines.length) {
        const item = lines[index].match(/^\s*(?:([-+*])\s+|(\d+)[.)]\s+)(.*)$/);
        if (!item || Boolean(item[2]) !== ordered) break;
        items.push(`<li>${markdownInline(item[3])}</li>`);
        index += 1;
      }
      const tag = ordered ? 'ol' : 'ul';
      blocks.push(`<${tag}>${items.join('')}</${tag}>`);
      continue;
    }

    paragraph.push(line);
    index += 1;
    if (index === lines.length || !lines[index].trim() || isMarkdownBlockStart(lines, index)) flushParagraph();
  }
  flushParagraph();
  return blocks.join('');
}
function messageHtml(message,user=false) {
  const content = user ? escapeHtml(message.text || '') : renderMarkdown(message.text || '');
  return `<div class="chat-row ${user?'user':''}"><div class="message-avatar">${user?escapeHtml(initials(state.user?.username)):'<svg><use href="#i-mark"/></svg>'}</div><div class="message-content"><div class="message-bubble">${content}</div><div class="message-meta">${user?'你':'AI 教练'} · ${escapeHtml(message.time||'刚刚')}</div></div></div>`;
}
function appendMessage(message) { if(!state.activeSessionId) return; state.chatMessages[state.activeSessionId] ||= []; state.chatMessages[state.activeSessionId].push(message); persistChatMessages(); renderChat(state.activeSessionId); }
function addTyping() { const box=$('#chatMessages'); const node=document.createElement('div'); node.id='typingMessage'; node.className='chat-row'; node.innerHTML='<div class="message-avatar"><svg><use href="#i-mark"/></svg></div><div class="message-content"><div class="message-bubble"><span class="typing-dots"><i></i><i></i><i></i></span></div><div class="message-meta">AI 教练 · 正在思考</div></div>'; box.appendChild(node); box.scrollTop=box.scrollHeight; }
function replaceTyping(text) { const node=$('#typingMessage'); if (!node) return; node.removeAttribute('id'); node.querySelector('.message-bubble').innerHTML=renderMarkdown(text); node.querySelector('.message-meta').textContent='AI 教练 · 刚刚'; }
function renderSources(sources = []) {
  const tray = $('#sourceTray');
  if (!sources.length) {
    tray.classList.add('hidden');
    tray.innerHTML = '';
    return;
  }

  const items = sources.map(source => {
    const index = Number(source.index);
    const reference = Number.isInteger(index) && index > 0
      ? `<span class="source-index">[${index}]</span> `
      : '';
    const score = source.score != null
      ? ` <small>相关度 ${escapeHtml(source.score)}</small>`
      : '';
    return `<li>${reference}${escapeHtml(source.documentTitle || '知识库资料')}${score}</li>`;
  }).join('');

  tray.classList.remove('hidden');
  tray.innerHTML = `<div class="message-sources"><strong>本次回答参考了 ${sources.length} 条资料</strong><ul>${items}</ul></div>`;
}
async function streamAnswer(query) {
  let sessionId=state.activeSessionId;
  if (!sessionId) {
    if (state.pendingInitialChat) { toast('正在创建新对话，请稍后再提交。'); return; }
    const accountGenerationBeforeCreation=state.accountGeneration;
    state.pendingInitialChat=true;
    const created=await createSession(query.slice(0,25));
    if(accountGenerationBeforeCreation===state.accountGeneration)state.pendingInitialChat=false;
    if(accountGenerationBeforeCreation!==state.accountGeneration||!created)return;
    sessionId=created.id;
  }
  if (state.chatStreams.isStreaming(sessionId)) { toast('当前对话正在回答，请等待完成或切换到其他对话。'); return; }

  const controller=new AbortController();
  const accountGeneration=state.accountGeneration;
  const ownerKey=String(state.user?.id??state.user?.username??'');
  const shouldNameSession=(state.chatMessages[sessionId]||[]).length===0;
  const userMessage={type:'user',text:query,time:'刚刚'};
  const stream=state.chatStreams.reserve(sessionId,{controller,accountGeneration,ownerKey,userMessage});
  if(!stream){toast('当前对话正在回答，请等待完成或切换到其他对话。');return;}
  appendChatMessage(sessionId,userMessage);
  renderActiveStream(sessionId,true);
  if(shouldNameSession)void nameSessionFromFirstQuestion(sessionId,query);

  let timedOut=false;
  const timeoutId=window.setTimeout(()=>{timedOut=true;controller.abort();},120000);
  try {
    const response=await fetch(apiUrl(`/ai/invoke_stream?session_id=${sessionId}&query=${encodeURIComponent(query)}&top_n=5&enable_web=false`),{method:'POST',headers:authHeaders(),signal:controller.signal});
    if(response.status===401){invalidateAuthentication();throw new Error('登录已过期');}
    if(!response.ok){let detail=null;try{detail=await response.json();}catch{}if(response.status===409){state.chatMessages[sessionId]=(state.chatMessages[sessionId]||[]).filter(message=>message!==userMessage);state.chatMessageRevision[sessionId]=(state.chatMessageRevision[sessionId]||0)+1;stream.userMessage=null;persistChatMessages();}throw new Error(parseError(detail,`AI 请求失败（${response.status}）`));}
    const completed=await consumeChatSse(response,{
      signal:controller.signal,
      isCurrent:()=>state.chatStreams.isCurrent(stream,state.accountGeneration),
      onEvent:(event,payload)=>{
        if(!state.chatStreams.isCurrent(stream,state.accountGeneration))return;
        if(event==='sources'){state.chatStreams.setSources(stream,accountGeneration,payload.sources||[]);renderActiveStream(sessionId,false,true);}
        if(event==='delta'){state.chatStreams.appendDelta(stream,accountGeneration,payload.text||'');renderActiveStream(sessionId);}
      },
    });
    if(!state.chatStreams.isCurrent(stream,state.accountGeneration))return;
    if(!completed)throw new Error('AI 流式响应未正常结束');
    const assistantMessage={type:'assistant',text:stream.answer||'AI 没有返回内容。',time:'刚刚',sources:stream.sources};
    state.chatStreams.setAssistant(stream,accountGeneration,assistantMessage);
    state.chatStreams.finish(stream,accountGeneration);
    appendChatMessage(sessionId,assistantMessage);
    renderActiveStream(sessionId);
  } catch(error) {
    if(!state.chatStreams.isCurrent(stream,state.accountGeneration))return;
    if(!controller.signal.aborted)controller.abort();
    state.chatStreams.fail(stream,accountGeneration,timedOut?'AI 回答超时，请重试。':(error?.message||'AI 回答失败'));
    renderActiveStream(sessionId);
    if(!timedOut&&error?.name!=='AbortError')showError(error);
  } finally {
    window.clearTimeout(timeoutId);
    if(state.chatStreams.get(sessionId)===stream&&stream.status==='streaming'){
      if(!controller.signal.aborted)controller.abort();
      state.chatStreams.fail(stream,accountGeneration,'回答已中断');
      renderActiveStream(sessionId,true);
    }
    if(state.activeSessionId===sessionId)updateChatComposerState();
    if(state.chatStreams.get(sessionId)===stream&&stream.status!=='streaming')renderSessions();
  }
}
async function sendChat(event) {
  event.preventDefault();
  const input = $('#chatInput');
  const query = input.value.trim();
  if (!query) return;

  if (isTrainingPlanIntent(query)) {
    input.value = '';
    state.chatDrafts.set(state.activeSessionId, '');
    input.style.height = 'auto';
    navigate('training');
    $('#trainingRequest').value = query;
    $('#trainingGenerateStatus').textContent = '已从 AI 教练带入训练计划需求；请检查后手动生成草稿，尚未保存。';
    $('#trainingRequest').focus({preventScroll: true});
    toast('已识别为训练计划需求，请检查并点击“生成计划草稿”。');
    return;
  }

  if(state.pendingInitialChat){toast('正在创建新对话，请稍后再提交。');return;}
  if(state.activeSessionId&&state.chatStreams.isStreaming(state.activeSessionId)){toast('当前对话正在回答，请等待完成或切换到其他对话。');return;}
  input.value = '';
  state.chatDrafts.set(state.activeSessionId, '');
  input.style.height = 'auto';
  await streamAnswer(query);
}
function renderTrainingPlan(plan, sources = [], generalNotes = [], saved = false) {
  const exerciseHtml = (exercise) => {
    const supported = exercise.evidence_type === 'knowledge_base' && exercise.source_refs?.length;
    const refs = supported ? exercise.source_refs.map((index, refIndex) => {
      const source = sources.find(item => item.index === index);
      const title = source?.documentTitle || exercise.source_titles?.[refIndex] || '';
      return `<span class="training-source-ref">[${index}] ${escapeHtml(title || '知识库资料')}</span>`;
    }).join('') : '';
    return `<li><div class="training-exercise-head"><strong>${escapeHtml(exercise.name)}</strong><span class="training-evidence ${supported?'is-supported':'is-general'}">${supported?'知识库支持':'一般建议'}</span></div><p>${exercise.sets} 组 × ${escapeHtml(exercise.reps)} 次 · 组间休息 ${exercise.rest_seconds} 秒</p>${exercise.notes?`<small>${escapeHtml(exercise.notes)}</small>`:''}${refs?`<div class="training-source-refs">${refs}</div>`:''}</li>`;
  };
  const days = (plan.days||[]).map(day => {
    const doneToday = saved && plan.id && TrainingWorkoutUI.wasPlanDayCompletedToday(state.trainingRecords, plan.id, day.day);
    const activeToday = saved && plan.id && TrainingWorkoutUI.findInProgressPlanWorkoutToday(state.trainingRecords, plan.id, day.day);
    const startButton = saved && plan.id ? activeToday
      ? `<button class="button button-light training-start-button" type="button" data-resume-workout="${Number(activeToday.id)}">继续进行中的训练</button>`
      : `<button class="button ${doneToday?'button-light':'button-dark'} training-start-button" type="button" data-start-workout="${Number(plan.id)}" data-start-workout-day="${escapeHtml(day.day)}" ${doneToday?'disabled':''}>${doneToday?'今日已完成':'开始这天训练'}</button>` : '';
    return `<article class="training-day"><div class="training-day-heading"><strong>${escapeHtml(day.day)}</strong><span>${escapeHtml(day.focus|| (day.is_rest_day?'休息':'训练'))}</span></div>${day.is_rest_day?'<p class="training-rest-label">休息日</p>':`<ul>${day.exercises.map(exerciseHtml).join('')}</ul>${startButton}`}</article>`;
  }).join('');
  const sourceHtml = sources.length ? `<details class="training-sources"><summary>本次检索资料 · ${sources.length} 条</summary><ul>${sources.map(source=>`<li>[${source.index}] ${escapeHtml(source.documentTitle)} · 相关度 ${source.score??'—'}</li>`).join('')}</ul></details>` : '<p class="training-no-sources">本次没有检索到知识库资料；动作均按一般建议标记。</p>';
  const notesHtml = generalNotes.length ? `<div class="training-general-notes"><strong>一般建议与待确认项</strong><ul>${generalNotes.map(note=>`<li>${escapeHtml(note)}</li>`).join('')}</ul></div>` : '';
  return `<div class="training-preview-heading"><div><p class="eyebrow">${saved?'SAVED PLAN':'DRAFT / NOT SAVED'}</p><h2>${escapeHtml(plan.title)}</h2><p>${escapeHtml(plan.goal||'未填写目标')} · ${escapeHtml(plan.experience||'未填写经验')}</p></div>${saved?'': '<button id="saveTrainingPlan" class="button button-primary" type="button"><svg><use href="#i-check"/></svg>确认并保存</button>'}</div><div class="training-days">${days}</div>${notesHtml}${sourceHtml}`;
}
async function generateTrainingPlan(event) {
  event.preventDefault();
  const button = $('#trainingGenerateButton');
  const status = $('#trainingGenerateStatus');
  const preview = $('#trainingPreview');
  const requestText = $('#trainingRequest').value.trim();
  if (!requestText) return;
  const owner = state.user?.id ?? state.user?.username;
  const accountGeneration = state.accountGeneration;
  button.disabled = true;
  status.textContent = '正在读取档案并检索资料、生成草稿…';
  preview.innerHTML = '<div class="empty-loading">正在生成计划草稿…</div>';
  state.trainingPreview = null;
  try {
    const profile = await syncFitnessProfile();
    if (accountGeneration !== state.accountGeneration || String(state.user?.id ?? state.user?.username ?? '') !== String(owner ?? '')) return;
    const prefills = applyTrainingProfileToForm(owner, profile);
    $('#trainingEquipment').value = prefills.equipment;
    $('#trainingDays').value = prefills.trainingDays;
    $('#trainingLimitations').value = prefills.limitations;
    const payload = {
      request: requestText,
      equipment: $('#trainingEquipment').value.trim() || null,
      training_days: $('#trainingDays').value ? Number($('#trainingDays').value) : null,
      limitations: $('#trainingLimitations').value.trim() || null,
    };
    const result = await request('/training/plans/generate', {method:'POST', body:JSON.stringify(payload)});
    if (accountGeneration !== state.accountGeneration || String(state.user?.id ?? state.user?.username ?? '') !== String(owner ?? '')) return;
    state.trainingPreview = result;
    preview.innerHTML = renderTrainingPlan(result.plan, result.sources, result.general_notes);
    status.textContent = profile ? '已结合当前账号档案；草稿尚未保存。' : '账号档案尚未填写；请检查草稿中的一般建议和假设。';
  } catch (error) {
    if (accountGeneration !== state.accountGeneration) return;
    preview.innerHTML = `<div class="empty-state"><div><h3>计划生成失败</h3><p>${escapeHtml(error.message)}</p></div></div>`;
    status.textContent = '草稿未保存。';
  } finally { if (accountGeneration === state.accountGeneration) button.disabled = false; }
}
async function saveTrainingPreview() {
  if (!state.trainingPreview?.plan) return;
  const button = $('#saveTrainingPlan');
  if (button) button.disabled = true;
  try {
    const saved = await request('/training/plans', {method:'POST', body:JSON.stringify(state.trainingPreview.plan)});
    state.trainingPreview.savedId = saved.id;
    $('#trainingPreview').innerHTML = renderTrainingPlan(saved, state.trainingPreview.sources, state.trainingPreview.general_notes, true);
    $('#trainingGenerateStatus').textContent = `已保存到当前账号，计划编号 ${saved.id}。`;
    toast('训练计划已保存。');
    await loadTrainingPlans();
  } catch (error) { if (button) button.disabled = false; showError(error); }
}
async function loadTrainingPlans() {
  const box = $('#trainingSavedPlans');
  if (!box) return;
  const accountGeneration = state.accountGeneration;
  box.innerHTML = '<div class="empty-loading">正在加载计划…</div>';
  try {
    const [plans] = await Promise.all([
      request('/training/plans?limit=50&offset=0'),
      loadTrainingProfileIntoForm(),
    ]);
    if (accountGeneration !== state.accountGeneration) return;
    box.innerHTML = plans.length ? plans.map(plan=>`<button class="training-saved-item" type="button" data-training-plan-id="${plan.id}"><strong>${escapeHtml(plan.title)}</strong><span>${escapeHtml(plan.goal||'未填写目标')} · ${plan.days.length} 天 · 更新于 ${formatDate(plan.update_at)}</span></button>`).join('') : '<div class="empty-state compact"><h3>还没有已保存的计划</h3><p>生成草稿并确认保存后，会显示在这里。</p></div>';
    await loadWorkoutHistory();
  } catch (error) { if (accountGeneration === state.accountGeneration) box.innerHTML = `<div class="empty-state compact"><h3>计划列表加载失败</h3><p>${escapeHtml(error.message)}</p></div>`; }
}
function readTrainingProfileFormValues() {
  return {
    equipment: $('#trainingEquipment').value,
    trainingDays: $('#trainingDays').value,
    limitations: $('#trainingLimitations').value,
  };
}
function applyTrainingProfileToForm(owner, profile) {
  let values = TrainingProfilePrefill.prepareTrainingProfileOwner(
    state.trainingProfilePrefill, owner, readTrainingProfileFormValues(),
  );
  values = TrainingProfilePrefill.applyTrainingProfilePrefill(
    state.trainingProfilePrefill, profile, values,
  );
  return values;
}
async function loadTrainingProfileIntoForm() {
  const owner = state.user?.id ?? state.user?.username;
  if (owner == null) return;
  const ownerKey = String(owner);
  const accountGeneration = state.accountGeneration;
  const initialValues = applyTrainingProfileToForm(owner, state.fitnessProfileOwner === ownerKey ? state.fitnessProfile : null);
  $('#trainingEquipment').value = initialValues.equipment;
  $('#trainingDays').value = initialValues.trainingDays;
  $('#trainingLimitations').value = initialValues.limitations;
  $('#trainingGenerateStatus').textContent = '正在读取当前账号档案…';
  try {
    const profile = await syncFitnessProfile();
    if (accountGeneration !== state.accountGeneration || String(state.user?.id ?? state.user?.username ?? '') !== ownerKey) return;
    const values = applyTrainingProfileToForm(owner, profile);
    $('#trainingEquipment').value = values.equipment;
    $('#trainingDays').value = values.trainingDays;
    $('#trainingLimitations').value = values.limitations;
    const hasTrainingDetails = profile && (profile.equipment || profile.weekly_training_days != null || profile.limitations);
    $('#trainingGenerateStatus').textContent = hasTrainingDetails
      ? '已将当前账号档案中的训练条件填入表单；可以修改后再生成。'
      : '档案未填写这三项；可以手动填写，未提供的信息不会被猜测。';
  } catch (error) {
    if (accountGeneration === state.accountGeneration && String(state.user?.id ?? state.user?.username ?? '') === ownerKey) {
      $('#trainingGenerateStatus').textContent = '档案读取失败；请手动填写训练条件后再生成。';
      console.warn('训练计划表单档案预填失败。', error);
    }
  }
}
async function openSavedTrainingPlan(id) {
  try {
    const plan = await request(`/training/plans/${id}`);
    const preview = $('#trainingPreview');
    state.currentTrainingPlan = plan;
    preview.innerHTML = renderTrainingPlan(plan, [], [], true);
    state.currentTrainingPlan = plan;
    state.trainingPreview = null;
    $('#trainingGenerateStatus').textContent = `已读取计划 ${plan.id}。`;
  } catch (error) { showError(error); }
}
function resetNutritionForm() {
  const form = $('#nutritionForm');
  if (!form) return;
  form.reset();
  $('#nutritionUnit').value = 'g';
  state.nutritionEditingId = null;
  $('#nutritionFormHeading').textContent = '记录一项食物';
  $('#saveNutritionRecord').innerHTML = '<svg><use href="#i-check"/></svg>保存记录';
  $('#cancelNutritionEdit').classList.add('hidden');
  $('#nutritionFormError').textContent = '';
}
async function loadNutritionDay() {
  const dateInput = $('#nutritionDate');
  const summaryBox = $('#nutritionSummary');
  const recordsBox = $('#nutritionRecords');
  if (!dateInput || !summaryBox || !recordsBox) return;
  if (!dateInput.value) dateInput.value = NutritionTrackingUI.todayLocalDate();
  const date = dateInput.value;
  const loadGeneration = ++state.nutritionLoadGeneration;
  const accountGeneration = state.accountGeneration;
  state.nutritionLoadedDate = date;
  summaryBox.innerHTML = '<div class="empty-loading">正在加载每日营养汇总…</div>';
  recordsBox.innerHTML = '<div class="empty-loading">正在加载饮食记录…</div>';
  try {
    const daily = await request(`/nutrition/daily?date=${encodeURIComponent(date)}`);
    if (loadGeneration !== state.nutritionLoadGeneration || accountGeneration !== state.accountGeneration || state.currentPage !== 'nutrition' || dateInput.value !== date) return;
    state.nutritionRecords = Array.isArray(daily.records) ? daily.records : [];
    summaryBox.innerHTML = NutritionTrackingUI.renderDailySummary(daily, escapeHtml);
    recordsBox.innerHTML = NutritionTrackingUI.renderNutritionRecords(state.nutritionRecords, escapeHtml);
    $('#nutritionRecordCount').textContent = `${state.nutritionRecords.length} 项`;
    await restoreNutritionPhotoPreview(accountGeneration);
  } catch (error) {
    if (loadGeneration !== state.nutritionLoadGeneration || accountGeneration !== state.accountGeneration) return;
    summaryBox.innerHTML = `<div class="nutrition-load-error" role="alert">每日汇总加载失败：${escapeHtml(error.message)}</div>`;
    recordsBox.innerHTML = `<div class="empty-state compact"><div><h3>暂时无法读取饮食记录</h3><p>${escapeHtml(error.message)}</p></div></div>`;
    $('#nutritionRecordCount').textContent = '—';
  }
}
function clearNutritionPhotoPreview() {
  const userId = state.user?.id ?? state.user?.username;
  if (userId != null) localStorage.removeItem(NutritionTrackingUI.photoPreviewStorageKey(userId));
  state.nutritionPhotoPreviewId = null;
  state.nutritionPhotoPreviewStatus = null;
  state.nutritionPhotoPreviewOwner = String(userId ?? '');
  releaseNutritionPhotoImage();
  $('#nutritionPhotoResult').innerHTML = '<p class="muted">选择图片后，识别结果会显示在这里供你核对。</p>';
}
function renderNutritionPhotoPreview(preview) {
  return NutritionTrackingUI.renderPhotoPreview(preview, escapeHtml);
}
function applyNutritionPhotoObjectUrl() {
  const image = $('#nutritionPhotoResult .nutrition-photo-image');
  if (!image || !state.nutritionPhotoObjectUrl) return;
  image.src = state.nutritionPhotoObjectUrl;
  image.hidden = false;
}
function releaseNutritionPhotoImage() {
  state.nutritionPhotoImageGeneration += 1;
  if (state.nutritionPhotoObjectUrl) URL.revokeObjectURL(state.nutritionPhotoObjectUrl);
  state.nutritionPhotoObjectUrl = null;
}
async function loadNutritionPhotoImage(previewId, accountGeneration, owner) {
  const imageGeneration = ++state.nutritionPhotoImageGeneration;
  try {
    const response = await fetch(apiUrl(`/nutrition/photos/${encodeURIComponent(previewId)}/image`), {headers:authHeaders()});
    if (response.status === 401) {
      invalidateAuthentication();
      throw new Error('登录已过期');
    }
    if (!response.ok) {
      let data = null;
      try { data = await response.json(); } catch {}
      throw new Error(parseError(data, `图片加载失败（${response.status}）`));
    }
    const image = await response.blob();
    if (imageGeneration !== state.nutritionPhotoImageGeneration || accountGeneration !== state.accountGeneration || owner !== String(state.user?.id ?? state.user?.username ?? '')) return;
    const objectUrl = URL.createObjectURL(image);
    const imageElement = $('#nutritionPhotoResult .nutrition-photo-image');
    if (!imageElement) {
      URL.revokeObjectURL(objectUrl);
      return;
    }
    if (state.nutritionPhotoObjectUrl) URL.revokeObjectURL(state.nutritionPhotoObjectUrl);
    state.nutritionPhotoObjectUrl = objectUrl;
    imageElement.src = objectUrl;
    imageElement.hidden = false;
  } catch (error) {
    const status = $('#nutritionPhotoStatus');
    if (imageGeneration === state.nutritionPhotoImageGeneration && accountGeneration === state.accountGeneration && status) {
      status.textContent = `图片预览加载失败：${error.message}`;
    }
  }
}
async function restoreNutritionPhotoPreview(accountGeneration = state.accountGeneration) {
  const userId = state.user?.id ?? state.user?.username;
  if (userId == null) return;
  const owner = String(userId);
  if (state.nutritionPhotoPreviewOwner === owner) return;
  state.nutritionPhotoPreviewOwner = owner;
  const key = NutritionTrackingUI.photoPreviewStorageKey(userId);
  const previewId = Number(localStorage.getItem(key));
  if (!Number.isSafeInteger(previewId) || previewId < 1) return;
  try {
    const preview = await request(`/nutrition/photos/${previewId}`);
    if (accountGeneration !== state.accountGeneration || owner !== String(state.user?.id ?? state.user?.username ?? '')) return;
    state.nutritionPhotoPreviewId = preview.id;
    state.nutritionPhotoPreviewStatus = preview.status;
    releaseNutritionPhotoImage();
    $('#nutritionPhotoResult').innerHTML = renderNutritionPhotoPreview(preview);
    applyNutritionPhotoObjectUrl();
    void loadNutritionPhotoImage(preview.id, accountGeneration, owner);
    $('#nutritionPhotoStatus').textContent = preview.status === 'confirmed' ? '该识别结果已经确认保存。' : '已恢复待确认的识别预览。';
  } catch (error) {
    if (accountGeneration !== state.accountGeneration) return;
    if (/404|不存在/.test(error.message)) localStorage.removeItem(key);
    else $('#nutritionPhotoStatus').textContent = `预览恢复失败：${error.message}`;
  }
}
async function createNutritionPhotoPreview(event) {
  event.preventDefault();
  const file = $('#nutritionPhotoInput').files[0];
  const status = $('#nutritionPhotoStatus');
  const button = $('#nutritionPhotoScan');
  if (!file) { status.textContent = '请先选择餐食图片。'; return; }
  if (state.nutritionPhotoPreviewStatus === 'preview') { status.textContent = '请先确认或取消当前待确认的识别预览。'; return; }
  if (file.size > 10 * 1024 * 1024) { status.textContent = '图片大小不能超过 10 MB。'; return; }
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { status.textContent = '仅支持 JPG、PNG 或 WebP 图片。'; return; }
  const accountGeneration = state.accountGeneration;
  const owner = String(state.user?.id ?? state.user?.username ?? '');
  button.disabled = true;
  status.textContent = '正在识别图片，尚未保存营养记录…';
  const form = new FormData();
  form.append('file', file);
  try {
    const response = await fetch(apiUrl('/nutrition/photos/preview'), {method:'POST', headers:authHeaders(), body:form});
    let data = null;
    try { data = await response.json(); } catch {}
    if (!response.ok) throw new Error(parseError(data, `识别请求失败（${response.status}）`));
    if (accountGeneration !== state.accountGeneration || owner !== String(state.user?.id ?? state.user?.username ?? '')) return;
    state.nutritionPhotoPreviewId = data.id;
    state.nutritionPhotoPreviewStatus = data.status;
    state.nutritionPhotoPreviewOwner = owner;
    localStorage.setItem(NutritionTrackingUI.photoPreviewStorageKey(owner), String(data.id));
    releaseNutritionPhotoImage();
    $('#nutritionPhotoResult').innerHTML = renderNutritionPhotoPreview(data);
    applyNutritionPhotoObjectUrl();
    void loadNutritionPhotoImage(data.id, accountGeneration, owner);
    status.textContent = '识别完成。结果为估算值，请核对并修改；此时尚未写入营养记录。';
  } catch (error) {
    status.textContent = error.message;
    showError(error);
  } finally {
    button.disabled = !$('#nutritionPhotoInput').files.length;
  }
}
function readNutritionPhotoItems() {
  return $$('#nutritionPhotoResult [data-photo-item-index]').map(row => {
    const item = {};
    row.querySelectorAll('[data-photo-field]').forEach(input => { item[input.dataset.photoField] = input.value; });
    return item;
  });
}
async function confirmNutritionPhotoPreview(button) {
  const previewId = Number(button.dataset.confirmPhoto);
  const errorBox = $('#nutritionPhotoResult .nutrition-photo-error');
  if (!Number.isSafeInteger(previewId) || previewId < 1) return;
  try {
    const payload = NutritionTrackingUI.buildPhotoConfirmPayload(readNutritionPhotoItems(), $('#nutritionDate').value);
    button.disabled = true;
    button.textContent = '正在保存…';
    await request(`/nutrition/photos/${previewId}/confirm`, {method:'POST', body:JSON.stringify(payload)});
    clearNutritionPhotoPreview();
    $('#nutritionPhotoInput').value = '';
    $('#nutritionPhotoScan').disabled = true;
    $('#nutritionPhotoStatus').textContent = '已确认保存为营养记录。';
    toast('图片识别结果已确认并保存。');
    await loadNutritionDay();
  } catch (error) {
    if (errorBox) errorBox.textContent = error.message;
    button.disabled = false;
    button.textContent = '确认并保存';
  }
}
async function cancelNutritionPhotoPreview(button) {
  const previewId = Number(button.dataset.cancelPhoto);
  if (!Number.isSafeInteger(previewId) || previewId < 1) return;
  button.disabled = true;
  try {
    await request(`/nutrition/photos/${previewId}`, {method:'DELETE'});
    clearNutritionPhotoPreview();
    $('#nutritionPhotoInput').value = '';
    $('#nutritionPhotoScan').disabled = true;
    $('#nutritionPhotoStatus').textContent = '本次识别预览已取消。';
  } catch (error) {
    const errorBox = $('#nutritionPhotoResult .nutrition-photo-error');
    if (errorBox) errorBox.textContent = error.message;
    button.disabled = false;
  }
}
function editNutritionRecord(record) {
  if (!record) return;
  state.nutritionEditingId = Number(record.id);
  $('#nutritionFoodName').value = record.food_name || '';
  $('#nutritionMealType').value = record.meal_type || 'breakfast';
  $('#nutritionAmount').value = record.amount ?? '';
  $('#nutritionUnit').value = record.unit || 'g';
  $('#nutritionCalories').value = record.calories_kcal ?? '';
  $('#nutritionProtein').value = record.protein_g ?? '';
  $('#nutritionCarbohydrate').value = record.carbohydrate_g ?? '';
  $('#nutritionFat').value = record.fat_g ?? '';
  $('#nutritionFormHeading').textContent = '修改饮食记录';
  $('#saveNutritionRecord').innerHTML = '<svg><use href="#i-check"/></svg>保存修改';
  $('#cancelNutritionEdit').classList.remove('hidden');
  $('#nutritionFormError').textContent = '';
  $('#nutritionFoodName').focus();
}
async function saveNutritionRecord(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const errorBox = $('#nutritionFormError');
  const button = $('#saveNutritionRecord');
  errorBox.textContent = '';
  let payload;
  try {
    payload = NutritionTrackingUI.buildNutritionPayload(Object.fromEntries(new FormData(form).entries()), $('#nutritionDate').value);
  } catch (error) {
    errorBox.textContent = error.message;
    return;
  }
  button.disabled = true;
  button.innerHTML = '<svg><use href="#i-check"/></svg>正在保存…';
  try {
    if (state.nutritionEditingId) {
      await request(`/nutrition/records/${state.nutritionEditingId}`, {method:'PUT', body:JSON.stringify(payload)});
      toast('饮食记录已更新。');
    } else {
      await request('/nutrition/records', {method:'POST', body:JSON.stringify(payload)});
      toast('饮食记录已保存。');
    }
    resetNutritionForm();
    await loadNutritionDay();
  } catch (error) {
    errorBox.textContent = error.message;
    showError(error);
  } finally {
    button.disabled = false;
    if (state.nutritionEditingId) button.innerHTML = '<svg><use href="#i-check"/></svg>保存修改';
    else if (button.textContent.includes('正在保存')) button.innerHTML = '<svg><use href="#i-check"/></svg>保存记录';
  }
}
async function deleteNutritionRecord(recordId, button) {
  const id = Number(recordId);
  if (!Number.isSafeInteger(id) || id < 1 || !window.confirm('确定删除这条饮食记录吗？')) return;
  if (button) { button.disabled = true; button.textContent = '删除中…'; }
  try {
    await request(`/nutrition/records/${id}`, {method:'DELETE'});
    if (state.nutritionEditingId === id) resetNutritionForm();
    toast('饮食记录已删除。');
    await loadNutritionDay();
  } catch (error) { if (button) { button.disabled = false; button.textContent = '删除'; } showError(error); }
}
function bindNutritionEvents() {
  $('#nutritionForm').addEventListener('submit', saveNutritionRecord);
  $('#nutritionDate').addEventListener('change', () => { resetNutritionForm(); loadNutritionDay(); });
  $('#nutritionToday').addEventListener('click', () => {
    $('#nutritionDate').value = NutritionTrackingUI.todayLocalDate();
    resetNutritionForm();
    loadNutritionDay();
  });
  $('#cancelNutritionEdit').addEventListener('click', resetNutritionForm);
  $('#nutritionRecords').addEventListener('click', event => {
    const editButton = event.target.closest('[data-edit-nutrition]');
    if (editButton) {
      const record = state.nutritionRecords.find(item => Number(item.id) === Number(editButton.dataset.editNutrition));
      return editNutritionRecord(record);
    }
    const deleteButton = event.target.closest('[data-delete-nutrition]');
    if (deleteButton) deleteNutritionRecord(deleteButton.dataset.deleteNutrition, deleteButton);
  });
  $('#nutritionPhotoForm').addEventListener('submit', createNutritionPhotoPreview);
  $('#nutritionPhotoInput').addEventListener('change', event => {
    $('#nutritionPhotoScan').disabled = !event.target.files.length;
    $('#nutritionPhotoStatus').textContent = event.target.files[0]?.name || '';
  });
  $('#nutritionPhotoResult').addEventListener('click', event => {
    const confirmButton = event.target.closest('[data-confirm-photo]');
    if (confirmButton) { confirmNutritionPhotoPreview(confirmButton); return; }
    const cancelButton = event.target.closest('[data-cancel-photo]');
    if (cancelButton) { cancelNutritionPhotoPreview(cancelButton); return; }
    const removeButton = event.target.closest('[data-remove-photo-item]');
    const addButton = event.target.closest('[data-add-photo-item]');
    if (!removeButton && !addButton) return;
    const preview = {
      id:state.nutritionPhotoPreviewId,
      status:'preview',
      image_url:`/nutrition/photos/${encodeURIComponent(state.nutritionPhotoPreviewId)}/image`,
      items:readNutritionPhotoItems(),
    };
    if (removeButton) preview.items.splice(Number(removeButton.dataset.removePhotoItem), 1);
    if (addButton && preview.items.length < 20) preview.items.push({meal_type:'snack', food_name:'', amount:'', unit:'g', calories_kcal:'0', protein_g:'0', carbohydrate_g:'0', fat_g:'0'});
    $('#nutritionPhotoResult').innerHTML = renderNutritionPhotoPreview(preview);
    applyNutritionPhotoObjectUrl();
    if (addButton) $('#nutritionPhotoResult [data-photo-item-index]:last-of-type [data-photo-field="food_name"]')?.focus();
  });
}
function renderWorkoutPanel(record) {
  const panel = $('#trainingWorkoutPanel');
  if (!panel) return;
  if (!record) { panel.classList.add('hidden'); panel.innerHTML = ''; return; }
  const exerciseFields = (record.exercises || []).map((exercise, index) => `
    <div class="workout-entry-row">
      <strong>${escapeHtml(exercise.name)}</strong>
      <span>计划 ${exercise.planned_sets || exercise.sets} 组 × ${escapeHtml(exercise.planned_reps || exercise.reps || '')} 次</span>
      <label>实际组数<input type="number" inputmode="numeric" min="1" max="30" value="${Number(exercise.sets || exercise.planned_sets || 1)}" data-workout-field="sets" data-workout-index="${index}"></label>
      <label>每组次数<input type="number" inputmode="numeric" min="1" max="300" value="${Number(exercise.reps || 1)}" data-workout-field="reps" data-workout-index="${index}"></label>
      <label>重量 kg <span>可留空</span><input type="number" inputmode="decimal" min="0" max="500" step="0.1" placeholder="自重留空" value="${exercise.weight_kg ?? ''}" data-workout-field="weight_kg" data-workout-index="${index}"></label>
    </div>`).join('');
  panel.classList.remove('hidden');
  panel.innerHTML = `<div class="training-workout-heading"><div><p class="eyebrow">WORKOUT IN PROGRESS</p><h2>${escapeHtml(record.plan_title)} · ${escapeHtml(record.plan_day)}</h2><p>${escapeHtml(record.focus || '训练')} · 完成后才会计入统计</p></div><button class="icon-button" type="button" data-close-workout aria-label="关闭">×</button></div><form id="workoutCompleteForm" class="workout-entry-form"><div class="workout-entry-list">${exerciseFields}</div><label>本次体重 kg <span>可留空</span><input type="number" inputmode="decimal" min="25" max="300" step="0.1" id="workoutBodyWeight" placeholder="可选"></label><div class="workout-form-actions"><button class="button button-dark" type="submit"><svg><use href="#i-check"/></svg>完成训练</button><button class="text-action danger" type="button" data-cancel-workout="${Number(record.id)}">取消本次训练</button></div></form>`;
}
async function startWorkout(planId, day) {
  try {
    const record = await request('/training/workouts', {method:'POST', body:JSON.stringify({plan_id:Number(planId), day})});
    state.activeWorkout = record;
    renderWorkoutPanel(record);
    $('#trainingWorkoutPanel').scrollIntoView({behavior:'smooth', block:'start'});
    toast('训练已开始，完成后才会计入统计。');
    await loadWorkoutHistory();
  } catch (error) { showError(error); }
}
async function completeActiveWorkout(event) {
  event.preventDefault();
  if (!state.activeWorkout) return;
  const payload = TrainingWorkoutUI.buildCompletionPayload(
    state.activeWorkout,
    (field, index) => $(`#workoutCompleteForm [data-workout-field="${field}"][data-workout-index="${index}"]`).value,
    $('#workoutBodyWeight').value,
  );
  const button = $('#workoutCompleteForm button[type="submit"]');
  button.disabled = true;
  try {
    await request(`/training/workouts/${Number(state.activeWorkout.id)}/complete`, {method:'POST', body:JSON.stringify(payload)});
    state.activeWorkout = null;
    renderWorkoutPanel(null);
    toast('训练已完成，统计数据已更新。');
    await loadWorkoutHistory();
    if (state.currentPage === 'dashboard') loadDashboard();
  } catch (error) { button.disabled = false; showError(error); }
}
async function cancelWorkout(id) {
  if (!window.confirm('取消后本次训练不会计入统计，确定取消吗？')) return;
  try { await request(`/training/workouts/${Number(id)}/cancel`, {method:'POST'}); if (state.activeWorkout?.id === Number(id)) { state.activeWorkout = null; renderWorkoutPanel(null); } await loadWorkoutHistory(); toast('本次训练已取消。'); } catch (error) { showError(error); }
}
async function resumeWorkout(id) {
  try { const record = await request(`/training/workouts/${Number(id)}`); state.activeWorkout = record; renderWorkoutPanel(record); $('#trainingWorkoutPanel').scrollIntoView({behavior:'smooth', block:'start'}); } catch (error) { showError(error); }
}
async function deleteWorkout(id) {
  if (!window.confirm('确定删除这条训练记录吗？删除后统计会重新计算。')) return;
  try { await request(`/training/workouts/${Number(id)}`, {method:'DELETE'}); await loadWorkoutHistory(); toast('训练记录已删除。'); } catch (error) { showError(error); }
}
async function loadWorkoutHistory() {
  const box = $('#trainingWorkoutHistory');
  if (!box) return;
  box.innerHTML = '<div class="empty-loading">正在加载训练记录…</div>';
  try {
    const {workouts: records, stats} = await TrainingWorkoutUI.fetchWorkoutHistoryData(request);
    state.trainingRecords = records;
    box.innerHTML = TrainingWorkoutUI.renderHistory(records);
    if ($('#trainingStatsGrid')) $('#trainingStatsGrid').innerHTML = TrainingWorkoutUI.renderStats(stats);
    if (state.currentTrainingPlan && $('#trainingPreview')) $('#trainingPreview').innerHTML = renderTrainingPlan(state.currentTrainingPlan, [], [], true);
  } catch (error) { box.innerHTML = `<div class="empty-state compact"><h3>训练记录加载失败</h3><p>${escapeHtml(error.message)}</p></div>`; }
}
async function loadDocuments(query='') { const grid=$('#documentGrid'); grid.innerHTML='<div class="empty-loading">正在取回你的训练资料…</div>'; try { let docs=[]; if(query){const results=await request(`/es/query?query=${encodeURIComponent(query)}`); docs=(Array.isArray(results)?results:results?.data||[]).map(item=>({id:item._id,title:item.title||`资料 ${item._id}`,summary:item.summary||item.content||'',status:1,doc_type:'搜索结果'}));} else docs=await request('/pg/check_all'); state.documents=docs||[]; $('#libraryCount').textContent=state.documents.length; renderDocuments(state.documents); } catch(error){grid.innerHTML=`<div class="empty-state"><div><div class="empty-state-icon"><svg><use href="#i-book"/></svg></div><h3>暂时取不到资料</h3><p>${escapeHtml(error.message)}</p></div></div>`;} }
function docType(doc){const title=String(doc.title||'').toLowerCase(); if(title.endsWith('.pdf'))return ['PDF','']; if(title.endsWith('.xlsx')||title.endsWith('.xls'))return ['XLS','type-xlsx']; if(title.endsWith('.pptx'))return ['PPT','type-pptx']; if(title.endsWith('.docx')||title.endsWith('.doc'))return ['DOC','type-docx']; return ['TXT',''];}
function docStatus(doc){if(doc.status===1)return ['已发布','is-published'];if(doc.status===3)return ['审核中','is-pending'];if(doc.parse_status===3)return ['解析失败','is-error'];if(doc.parse_status===1)return ['处理中',''];return ['草稿',''];}
function renderDocuments(docs){const grid=$('#documentGrid');if(!docs.length){grid.innerHTML='<div class="empty-state"><div><div class="empty-state-icon"><svg><use href="#i-plus"/></svg></div><h3>知识库还没有训练资料</h3><p>上传一份训练、营养或恢复相关资料，<br>再让 AI 教练用它来回答问题。</p><button data-open-upload>上传第一份资料</button></div></div>';return;}grid.innerHTML=docs.map(doc=>{const [type,typeClass]=docType(doc);const [status,statusClass]=docStatus(doc);const canSubmit=doc.status!==1&&doc.status!==3&&doc.id&&Number(doc.author_id)===Number(state.user?.id);return `<article class="document-card"><div class="document-card-top"><span class="doc-type-mark ${typeClass}">${type}</span><span class="doc-status ${statusClass}">${status}</span></div><h3 title="${escapeHtml(doc.title||'未命名资料')}">${escapeHtml(doc.title||'未命名资料')}</h3><p>${escapeHtml(doc.summary||'这份资料暂时没有摘要。')}</p><div class="doc-meta"><span>${escapeHtml(doc.uploader||'训练知识库')}</span><span class="parse-state ${statusClass==='is-error'?'is-error':doc.parse_status===1?'is-running':''}"><i></i>${doc.parse_status===2?'已完成':doc.parse_status===1?'处理中':'可查看'}</span></div><div class="document-card-actions">${canSubmit?`<button class="publish-doc" data-publish-doc="${doc.id}">提交审核</button>`:''}<button data-view-doc="${doc.id}">查看</button><button class="delete-doc" data-delete-doc="${doc.id}" aria-label="删除资料">删除</button></div></article>`;}).join('');}
async function publishDocument(id){try{await request('/review/submit',{method:'POST',body:JSON.stringify({doc_id:Number(id)})});toast('资料已提交审核。');await loadDocuments();}catch(error){showError(error);}}
async function deleteDocument(id){if(!window.confirm('删除后会同步清理文档内容和索引，确定继续吗？'))return;try{await request(`/pg/del_doc?doc_id=${id}`,{method:'DELETE'});toast('资料已删除。');await loadDocuments();}catch(error){showError(error);}}
async function loadDocDetail(id){try{const doc=await request(`/pg/check?id=${id}`);toast(`${doc.title||'资料'} · ${doc.summary||'暂无摘要'}`);}catch(error){showError(error);}}
async function uploadFile(){const input=$('#fileInput');const file=input.files[0];if(!file)return;const button=$('#uploadButton');const status=$('#uploadStatus');button.disabled=true;status.textContent='正在上传并解析…';const form=new FormData();form.append('file',file);try{const response=await fetch(apiUrl('/restfs/upload'),{method:'POST',headers:authHeaders(),body:form});let data=null;try{data=await response.json()}catch{}if(!response.ok)throw new Error(parseError(data,`上传失败（${response.status}）`));status.textContent='上传成功，已保存为草稿。';toast('资料上传成功，可提交审核。');setTimeout(()=>{$('#uploadPanel').classList.add('hidden');loadDocuments()},600);}catch(error){status.textContent=error.message;showError(error);}finally{button.disabled=false;}}
function fillProfileForm(profile={}){$('#heightInput').value=profile.height??'';$('#weightInput').value=profile.weight??'';$('#ageInput').value=profile.age??'';$('#sexInput').value=profile.sex??'';$('#goalInput').value=profile.goal??'';$('#experienceInput').value=profile.experience??'';$('#weeklyTrainingDaysInput').value=profile.weekly_training_days??'';$('#equipmentInput').value=profile.equipment??'';$('#limitationsInput').value=profile.limitations??'';}
async function loadProfile(){const saveState=$('#profileSaveState');saveState.textContent='正在读取账号档案…';try{const saved=await syncFitnessProfile(true);const globalDraft=!saved?readStoredJson('ironflow_profile',null):null;const hasGlobalDraft=globalDraft&&typeof globalDraft==='object'&&!Array.isArray(globalDraft);fillProfileForm(saved|| (hasGlobalDraft?globalDraft:{}));saveState.textContent=hasGlobalDraft?'检测到旧版本机档案，请核对后手动保存':saved?'已保存到账号数据库':'尚未填写';}catch(error){const draft=readStoredJson(profileStorageKey(),{})||{};fillProfileForm(draft);saveState.textContent='云端读取失败；本机旧档案未删除';showError(error);}$('#profileEmailInput').value=state.user?.email||'';updateUserUI();checkApi();}
async function saveAccountProfile(data){if(!state.user?.id)return;const email=(data.email||'').trim();if(!email||email===state.user.email)return;const updated=await request('/user/update_user?user_id='+encodeURIComponent(state.user.id),{method:'PUT',body:JSON.stringify({email})});state.user={...state.user,...updated};localStorage.setItem('ironflow_user',JSON.stringify(state.user));updateUserUI();}
async function saveProfile(event){event.preventDefault();const payload=profilePayload({height:$('#heightInput').value,weight:$('#weightInput').value,age:$('#ageInput').value,sex:$('#sexInput').value,goal:$('#goalInput').value,experience:$('#experienceInput').value,weekly_training_days:$('#weeklyTrainingDaysInput').value,equipment:$('#equipmentInput').value,limitations:$('#limitationsInput').value});const saveState=$('#profileSaveState');saveState.textContent='正在保存到账号数据库…';try{const saved=await request('/fitness/profile',{method:'PUT',body:JSON.stringify(payload)});state.fitnessProfileOwner=String(state.user?.id??state.user?.username??'');state.fitnessProfile=saved;state.fitnessProfileLoaded=true;localStorage.removeItem(profileStorageKey());saveState.textContent='已保存到账号数据库';try{await saveAccountProfile({email:$('#profileEmailInput').value});toast('健身档案已保存到账号数据库，AI 问答会按登录账号读取。');}catch(error){toast('健身档案已保存；账号邮箱同步失败：'+error.message);}}catch(error){saveState.textContent='保存失败，请检查填写内容或后端连接';showError(error);}}
function adminPermissionCodes(nodes, output=[]){(nodes||[]).forEach(node=>{output.push(node);adminPermissionCodes(node.children,output)});return output;}
function adminStatusLabel(status){return status===1?'已通过':status===2?'已驳回':'待审核';}
function adminStatusClass(status){return status===1?'is-approved':status===2?'is-rejected':'is-pending';}
function adminSetTab(tab){if(state.admin.isReviewer&&!state.admin.isAdmin&&tab!=='reviews')return;state.admin.tab=tab;$$('.admin-tab').forEach(button=>button.classList.toggle('active',button.dataset.adminTab===tab));$$('.admin-panel').forEach(panel=>panel.classList.toggle('active',panel.dataset.adminPanel===tab));if(tab==='users')loadAdminUsers();if(tab==='reviews')loadAdminReviews();if(tab==='roles')loadAdminRoles();if(tab==='teams')loadAdminTeams();if(tab==='system')loadAdminSystem();}
function adminPager(target,total,page,pageSize,handler){const pages=Math.max(1,Math.ceil((total||0)/pageSize));const node=$(target);if(!node)return;node.innerHTML=`<span>第 ${page} / ${pages} 页 · 共 ${total||0} 条</span><div><button class="icon-button" data-admin-page="prev" ${page<=1?'disabled':''} aria-label="上一页">‹</button><button class="icon-button" data-admin-page="next" ${page>=pages?'disabled':''} aria-label="下一页">›</button></div>`;node.onclick=event=>{const button=event.target.closest('[data-admin-page]');if(!button||button.disabled)return;handler(button.dataset.adminPage==='next'?page+1:page-1)};}
function adminRoleName(code){const standardNames={ROLE_ADMIN:'系统管理员',ROLE_SH:'审核员',ROLE_USER:'普通用户'};if(standardNames[code])return standardNames[code];const role=state.admin.roles.find(item=>item.role_code===code);return role?.role_name||'自定义角色';}
function applyAdminRoleCodes(codes){state.admin.roleCodes=codes;state.admin.isAdmin=codes.includes('ROLE_ADMIN');state.admin.isReviewer=codes.includes('ROLE_SH');state.admin.allowed=state.admin.isAdmin||state.admin.isReviewer;$('.nav-item-admin')?.classList.toggle('hidden',!state.admin.allowed);$('#adminRoleBadge').textContent=codes.length?codes.map(adminRoleName).join(' · '):'普通用户';}
async function updateAdminNavigation(){const generation=state.accountGeneration;const userId=state.user?.id;if(!userId){$('.nav-item-admin')?.classList.add('hidden');return;}try{const result=await request(`/user/roles?user_id=${encodeURIComponent(userId)}`);if(generation===state.accountGeneration&&String(state.user?.id)===String(userId))applyAdminRoleCodes(result?.role_codes||[]);}catch{$('.nav-item-admin')?.classList.add('hidden');}}
function setAdminRoleView(){const reviewerOnly=state.admin.isReviewer&&!state.admin.isAdmin;$('#adminKpis').classList.toggle('hidden',reviewerOnly);$$('.admin-tab').forEach(button=>button.classList.toggle('hidden',reviewerOnly&&button.dataset.adminTab!=='reviews'));$$('.admin-panel').forEach(panel=>panel.classList.toggle('hidden',reviewerOnly&&panel.dataset.adminPanel!=='reviews'));$('#page-admin .page-subtitle').textContent=reviewerOnly?'仅显示当前账号获授权团队的审核任务。':'把用户、知识审核和团队协作放在同一个清晰的工作区。';if(reviewerOnly)state.admin.tab='reviews';}
async function ensureAdminAccess(){if(!state.user?.id)return false;try{const result=await request(`/user/roles?user_id=${encodeURIComponent(state.user.id)}`);applyAdminRoleCodes(result?.role_codes||[]);if(!state.admin.allowed){$('#adminWorkspace').classList.add('hidden');$('#adminAccessState').classList.remove('hidden');$('#adminAccessState').innerHTML='<span class="admin-access-icon"><svg><use href="#i-shield"/></svg></span><div><span class="admin-access-kicker">权限状态 · 普通用户</span><strong>当前账号没有管理或审核权限</strong><p>当前账号可以使用训练、知识库和 AI 教练功能；管理台仅对系统管理员和审核员开放。</p><button class="button button-light admin-back-button" data-go="dashboard">返回今日训练 <svg><use href="#i-arrow"/></svg></button></div>';return false;}setAdminRoleView();$('#adminAccessState').classList.add('hidden');$('#adminWorkspace').classList.remove('hidden');return true;}catch(error){$('#adminWorkspace').classList.add('hidden');$('#adminAccessState').classList.remove('hidden');$('#adminAccessState').innerHTML=`<span class="admin-access-icon"><svg><use href="#i-close"/></svg></span><div><span class="admin-access-kicker">连接状态 · 未知</span><strong>管理台暂时无法连接</strong><p>${escapeHtml(error.message)}</p><button class="button button-light admin-back-button" data-go="dashboard">返回今日训练 <svg><use href="#i-arrow"/></svg></button></div>`;return false;}}
async function loadAdmin(){if(!(await ensureAdminAccess()))return;if(state.admin.isAdmin)await loadAdminOverview();adminSetTab(state.admin.tab);}
async function loadAdminOverview(){try{const [users,pending,teams,docs]=await Promise.all([request('/user/query_users?page=1&page_size=1'),request('/review/pending_count'),request('/team/query_team?page=1&page_size=1'),request('/pg/check_all')]);$('#adminUserCount').textContent=users?.total??'0';$('#adminPendingCount').textContent=pending?.count??'0';$('#adminTeamCount').textContent=teams?.total??'0';$('#adminDocCount').textContent=Array.isArray(docs)?docs.length:'0';}catch(error){['adminUserCount','adminPendingCount','adminTeamCount','adminDocCount'].forEach(id=>$(id).textContent='—');showError(error);}}
async function loadAdminUsers(){const box=$('#adminUsersTable');box.innerHTML='<div class="empty-loading">正在加载用户…</div>';try{if(!state.admin.roles.length){try{const roles=await request('/role/get_roles');state.admin.roles=Array.isArray(roles)?roles:[]}catch{}}const query=new URLSearchParams({username:state.admin.userKeyword,page:String(state.admin.usersPage),page_size:'10'});const result=await request(`/user/query_users?${query}`);const rows=result?.list||[];box.innerHTML=rows.length?`<table class="admin-table"><thead><tr><th>用户</th><th>邮箱</th><th>角色</th><th>团队</th><th>加入时间</th><th>操作</th></tr></thead><tbody>${rows.map(user=>`<tr><td><div class="table-person"><span class="table-avatar">${escapeHtml(initials(user.username))}</span><span><strong>${escapeHtml(user.username)}</strong><small>ID ${user.id}</small></span></div></td><td>${escapeHtml(user.email||'—')}</td><td><div class="tag-list">${(user.role_codes||[]).map(code=>`<span class="tag">${escapeHtml(adminRoleName(code))}</span>`).join('')||'<span class="muted">未分配</span>'}</div></td><td>${escapeHtml(user.team_name||'未加入')}</td><td>${formatDate(user.create_at)}</td><td><div class="table-actions"><button class="text-action" data-admin-edit-user="${user.id}">编辑</button><button class="text-action admin-role-trigger" data-admin-user-roles="${user.id}" data-admin-user-name="${escapeHtml(user.username)}" aria-haspopup="dialog" aria-expanded="false">分配角色 <svg><use href="#i-chevron"/></svg></button><button class="text-action danger" data-admin-delete-user="${user.id}">删除</button></div></td></tr>`).join('')}</tbody></table>`:'<div class="empty-state compact"><h3>还没有匹配用户</h3><p>可以创建一个新的训练者账号。</p></div>';adminPager('#adminUsersPagination',result?.total||0,state.admin.usersPage,10,page=>{state.admin.usersPage=page;loadAdminUsers()});}catch(error){box.innerHTML=`<div class="empty-state compact"><h3>用户列表加载失败</h3><p>${escapeHtml(error.message)}</p></div>`;}}
async function loadAdminReviews(){const box=$('#adminReviewsTable');box.innerHTML='<div class="empty-loading">正在加载审核任务…</div>';try{const query=new URLSearchParams({status:state.admin.reviewStatus,page:String(state.admin.reviewsPage),page_size:'10'});const result=await request(`/review/tasks?${query}`);const rows=result?.list||[];const emptyTitle=state.admin.reviewStatus==='pending'?'当前没有待审核内容':'暂无这类审核记录';box.innerHTML=rows.length?`<table class="admin-table"><thead><tr><th>资料</th><th>任务</th><th>提交时间</th><th>审核人</th><th>状态</th><th>操作</th></tr></thead><tbody>${rows.map(task=>`<tr><td><strong>${escapeHtml(task.title||`文档 #${task.doc_id}`)}</strong><small class="table-sub">DOC ${task.doc_id}</small></td><td>#${task.id}</td><td>${formatDate(task.create_at)}</td><td>${escapeHtml(task.reviewer_name||'—')}</td><td><span class="status-chip ${adminStatusClass(task.review_result)}">${adminStatusLabel(task.review_result)}</span>${task.review_comment?`<small class="table-sub">${escapeHtml(task.review_comment)}</small>`:''}</td><td>${task.review_result==null&&task.can_review?`<div class="table-actions"><button class="text-action" data-review-action="approve" data-review-id="${task.id}">通过</button><button class="text-action danger" data-review-action="reject" data-review-id="${task.id}">驳回</button></div>`:'<span class="muted">只读</span>'}</td></tr>`).join('')}</tbody></table>`:`<div class="empty-state compact"><h3>${emptyTitle}</h3><p>资料提交审核后会出现在这里。</p></div>`;adminPager('#adminReviewsPagination',result?.total||0,state.admin.reviewsPage,10,page=>{state.admin.reviewsPage=page;loadAdminReviews()});}catch(error){box.innerHTML=`<div class="empty-state compact"><h3>审核列表加载失败</h3><p>${escapeHtml(error.message)}</p></div>`;}}
async function loadAdminRoles(){const box=$('#adminRolesTable');box.innerHTML='<div class="empty-loading">正在加载角色…</div>';try{state.admin.roles=await request('/role/get_roles');box.innerHTML=state.admin.roles.length?`<table class="admin-table"><thead><tr><th>角色</th><th>编码</th><th>说明</th><th>成员</th><th>操作</th></tr></thead><tbody>${state.admin.roles.map(role=>`<tr><td><strong>${escapeHtml(adminRoleName(role.role_code))}</strong><small class="table-sub">ID ${role.id}</small></td><td><span class="code-pill">${escapeHtml(role.role_code)}</span></td><td>${escapeHtml(role.description||'—')}</td><td>${role.users?.length||0} 人</td><td><div class="table-actions"><button class="text-action" data-admin-permissions="${role.id}">权限</button><button class="text-action" data-admin-edit-role="${role.id}">编辑</button><button class="text-action danger" data-admin-delete-role="${role.id}" ${['ROLE_ADMIN','ROLE_SH','ROLE_USER'].includes(role.role_code)?'disabled title="系统内置角色不可删除"':''}>删除</button></div></td></tr>`).join('')}</tbody></table>`:'<div class="empty-state compact"><h3>还没有角色</h3><p>创建角色后，再为它分配权限。</p></div>';}catch(error){box.innerHTML=`<div class="empty-state compact"><h3>角色加载失败</h3><p>${escapeHtml(error.message)}</p></div>`;}}
async function loadAdminPermissions(roleId){const editor=$('#permissionEditor');editor.classList.remove('hidden');editor.innerHTML='<div class="empty-loading">正在加载权限树…</div>';try{if(!state.admin.permissions.length)state.admin.permissions=adminPermissionCodes(await request('/permission/tree'));const selected=new Set((await request(`/role/permissions?role_id=${roleId}`))?.permission_ids||[]);editor.innerHTML=`<div class="permission-editor-head"><div><span class="eyebrow">ROLE ACCESS</span><h3>配置角色权限</h3></div><button class="icon-button" data-close-permissions aria-label="关闭">×</button></div><div class="permission-grid">${state.admin.permissions.map(permission=>`<label class="permission-option ${permission.permission_type===1?'permission-parent':''}"><input type="checkbox" value="${permission.id}" ${selected.has(permission.id)?'checked':''}><span><strong>${escapeHtml(permission.permission_name)}</strong><small>${escapeHtml(permission.permission_code)}</small></span></label>`).join('')}</div><button class="button button-primary" data-save-permissions="${roleId}">保存权限 <svg><use href="#i-check"/></svg></button>`;}catch(error){editor.innerHTML=`<div class="empty-state compact"><h3>权限加载失败</h3><p>${escapeHtml(error.message)}</p></div>`;}}
async function loadAdminTeams(){const box=$('#adminTeamsTable');box.innerHTML='<div class="empty-loading">正在加载团队…</div>';try{const result=await request('/team/query_team?page=1&page_size=100');state.admin.teams=result?.list||[];box.innerHTML=state.admin.teams.length?`<table class="admin-table"><thead><tr><th>团队</th><th>编码</th><th>说明</th><th>成员</th><th>状态</th><th>操作</th></tr></thead><tbody>${state.admin.teams.map(team=>`<tr><td><strong>${escapeHtml(team.team_name)}</strong><small class="table-sub">ID ${team.id}</small></td><td><span class="code-pill">${escapeHtml(team.team_code)}</span></td><td>${escapeHtml(team.description||'—')}</td><td>${team.member_count||0} 人</td><td><span class="status-chip ${team.status===1?'is-approved':'is-pending'}">${team.status===1?'启用':'停用'}</span></td><td><div class="table-actions"><button class="text-action" data-admin-members="${team.id}">成员</button><button class="text-action" data-admin-edit-team="${team.id}">编辑</button><button class="text-action danger" data-admin-delete-team="${team.id}">删除</button></div></td></tr>`).join('')}</tbody></table>`:'<div class="empty-state compact"><h3>还没有团队</h3><p>创建一个团队，开始组织训练内容和审核范围。</p></div>';}catch(error){box.innerHTML=`<div class="empty-state compact"><h3>团队加载失败</h3><p>${escapeHtml(error.message)}</p></div>`;}}
async function loadAdminSystem(){const box=$('#adminSystemGrid');box.innerHTML='<div class="empty-loading">正在检查服务…</div>';const checks=[{name:'后端 API',detail:'/docs',run:()=>fetch(apiUrl('/docs'),{headers:authHeaders(),signal:timeoutSignal(5000)})},{name:'PostgreSQL / 文档',detail:'/pg/check_all',run:()=>request('/pg/check_all')},{name:'权限服务',detail:'/permission/tree',run:()=>request('/permission/tree')},{name:'Neo4j 图谱',detail:'/neo4j/overview',run:()=>request('/neo4j/overview')}];const results=await Promise.all(checks.map(async check=>{try{const response=await check.run();if(response instanceof Response&&!response.ok)throw new Error(`HTTP ${response.status}`);return {...check,ok:true};}catch(error){return {...check,ok:false,error:error.message};}}));box.innerHTML=results.map(result=>`<article class="system-status-card ${result.ok?'is-online':'is-offline'}"><span class="system-status-dot"></span><div><strong>${escapeHtml(result.name)}</strong><small>${escapeHtml(result.detail)}</small></div><b>${result.ok?'正常':'异常'}</b>${result.error?`<p>${escapeHtml(result.error)}</p>`:''}</article>`).join('');}
async function adminCreateUser(){const username=window.prompt('用户名');if(!username)return;const email=window.prompt('邮箱');if(!email)return;const password=window.prompt('初始密码（至少 6 位）');if(!password)return;try{await request('/user/create_user',{method:'POST',body:JSON.stringify({username,email,password,role_codes:[]})});toast('用户已创建。');loadAdminUsers();loadAdminOverview();}catch(error){showError(error);}}
async function adminEditUser(id){const result=await request(`/user/query_users?username=&page=1&page_size=100`);const user=(result?.list||[]).find(item=>item.id===Number(id));if(!user)return;const username=window.prompt('用户名',user.username);if(username===null)return;const email=window.prompt('邮箱',user.email||'');if(email===null)return;const password=window.prompt('新密码（留空则不修改）','');if(password===null)return;const body={username:username.trim(),email:email.trim()};if(password.trim())body.password=password.trim();try{await request(`/user/update_user?user_id=${id}`,{method:'PUT',body:JSON.stringify(body)});toast('用户资料已更新。');loadAdminUsers();}catch(error){showError(error);}}
function closeAdminRolePopover(restoreFocus=true){const editor=adminRolePopover;if(!editor)return;document.removeEventListener('pointerdown',editor.onOutside,true);document.removeEventListener('keydown',editor.onKeydown);document.removeEventListener('scroll',editor.onScroll,true);window.removeEventListener('resize',editor.onResize);editor.anchor.setAttribute('aria-expanded','false');editor.panel.remove();adminRolePopover=null;if(restoreFocus&&editor.anchor.isConnected)editor.anchor.focus();}
function positionAdminRolePopover(panel,anchor){if(!panel.isConnected||!anchor.isConnected)return;const rect=anchor.getBoundingClientRect();const width=Math.min(320,window.innerWidth-24);panel.style.width=`${width}px`;const left=Math.max(12,Math.min(rect.left,window.innerWidth-width-12));const height=panel.offsetHeight;const top=rect.bottom+8+height>window.innerHeight-12?Math.max(12,rect.top-height-8):rect.bottom+8;panel.style.left=`${left}px`;panel.style.top=`${top}px`;}
async function adminAssignRoles(userId,userName,anchor){closeAdminRolePopover(false);const panel=document.createElement('section');panel.className='admin-role-popover';panel.setAttribute('role','dialog');panel.setAttribute('aria-label',`为${userName}分配角色`);panel.innerHTML=`<div class="admin-role-popover-head"><div><span class="eyebrow">用户权限</span><h3>为 ${escapeHtml(userName)} 分配角色</h3></div><button type="button" class="icon-button" data-close-role-popover aria-label="关闭"><svg><use href="#i-close"/></svg></button></div><div class="admin-role-popover-body"><div class="admin-role-loading">正在读取角色…</div></div><div class="admin-role-popover-actions"><button type="button" class="text-action" data-cancel-role-popover>取消</button><button type="button" class="button button-primary" data-save-user-roles disabled>保存角色</button></div>`;document.body.append(panel);anchor.setAttribute('aria-expanded','true');const editor={panel,anchor};adminRolePopover=editor;editor.onOutside=event=>{if(!panel.contains(event.target)&&!anchor.contains(event.target))closeAdminRolePopover(false)};editor.onKeydown=event=>{if(event.key==='Escape')closeAdminRolePopover()};editor.onScroll=event=>{if(!panel.contains(event.target))closeAdminRolePopover(false);else positionAdminRolePopover(panel,anchor)};editor.onResize=()=>positionAdminRolePopover(panel,anchor);panel.addEventListener('click',async event=>{if(event.target.closest('[data-close-role-popover],[data-cancel-role-popover]'))return closeAdminRolePopover();const save=event.target.closest('[data-save-user-roles]');if(!save||save.disabled)return;const selected=$$('input[name="admin-user-role"]:checked',panel).map(input=>input.value);const codes=[...new Set([...editor.unavailableCodes,...selected])];const cancel=$('[data-cancel-role-popover]',panel);save.disabled=true;cancel.disabled=true;save.textContent='正在保存…';try{await request('/user/assign_roles',{method:'POST',body:JSON.stringify({user_id:Number(userId),role_codes:codes})});closeAdminRolePopover(false);toast('角色已更新。');loadAdminUsers();}catch(error){showError(error);save.disabled=false;cancel.disabled=false;save.textContent='保存角色';}});panel.addEventListener('change',()=>{$('.admin-role-selected-count',panel).textContent=`已选 ${$$('input[name="admin-user-role"]:checked',panel).length} 个角色`});document.addEventListener('pointerdown',editor.onOutside,true);document.addEventListener('keydown',editor.onKeydown);document.addEventListener('scroll',editor.onScroll,true);window.addEventListener('resize',editor.onResize);positionAdminRolePopover(panel,anchor);try{const roleRequest=state.admin.roles.length?Promise.resolve(state.admin.roles):request('/role/get_roles');const [roles,current]=await Promise.all([roleRequest,request(`/user/roles?user_id=${encodeURIComponent(userId)}`)]);if(adminRolePopover!==editor)return;state.admin.roles=Array.isArray(roles)?roles:[];const currentCodes=Array.isArray(current?.role_codes)?current.role_codes:[];const knownCodes=new Set(state.admin.roles.map(role=>role.role_code));editor.unavailableCodes=currentCodes.filter(code=>!knownCodes.has(code));const options=state.admin.roles.map(role=>`<label class="admin-role-option"><input type="checkbox" name="admin-user-role" value="${escapeHtml(role.role_code)}" ${currentCodes.includes(role.role_code)?'checked':''}><span><strong>${escapeHtml(adminRoleName(role.role_code))}</strong></span></label>`).join('');const warning=editor.unavailableCodes.length?`<p class="admin-role-warning">有 ${editor.unavailableCodes.length} 个当前角色无法显示，保存时会保留。</p>`:'';panel.querySelector('.admin-role-popover-body').innerHTML=options?`<p class="admin-role-selected-count">已选 ${currentCodes.filter(code=>knownCodes.has(code)).length} 个角色</p><div class="admin-role-options">${options}</div>${warning}`:'<div class="admin-role-empty">暂无可分配角色，请先在“角色权限”中创建角色。</div>';const save= $('[data-save-user-roles]',panel);save.disabled=!state.admin.roles.length;positionAdminRolePopover(panel,anchor);panel.querySelector('input[name="admin-user-role"]')?.focus();}catch(error){if(adminRolePopover===editor){closeAdminRolePopover(false);showError(error);}}}
async function adminDeleteUser(id){if(!window.confirm('确定删除这个用户吗？此操作不可撤销。'))return;try{await request(`/user/del_user?user_id=${id}`,{method:'DELETE'});toast('用户已删除。');loadAdminUsers();loadAdminOverview();}catch(error){showError(error);}}
async function adminReviewAction(id,result){let comment='';if(result===2){comment=window.prompt('请输入驳回意见（必填）')||'';if(!comment.trim())return toast('驳回必须填写意见。');}if(!window.confirm(result===1?'确认通过这条资料？':'确认驳回这条资料？'))return;try{await request('/review/action',{method:'POST',body:JSON.stringify({task_id:Number(id),result,comment:comment.trim()||null})});toast(result===1?'资料已通过审核。':'资料已驳回。');loadAdminReviews();if(state.admin.isAdmin)loadAdminOverview();}catch(error){showError(error);}}
async function adminCreateRole(){const role_name=window.prompt('角色名称');if(!role_name)return;const role_code=window.prompt('角色编码，例如 ROLE_COACH');if(!role_code)return;const description=window.prompt('角色说明')||'';try{await request('/role/add_role',{method:'POST',body:JSON.stringify({role_name,role_code,description})});toast('角色已创建。');loadAdminRoles();}catch(error){showError(error);}}
async function adminEditRole(id){const role=state.admin.roles.find(item=>item.id===Number(id));if(!role)return;const role_name=window.prompt('角色名称',role.role_name);if(role_name===null)return;const description=window.prompt('角色说明',role.description||'');if(description===null)return;try{await request(`/role/update_role?role_id=${id}`,{method:'PUT',body:JSON.stringify({role_name,description})});toast('角色已更新。');loadAdminRoles();}catch(error){showError(error);}}
async function adminDeleteRole(id){if(!window.confirm('删除角色会清理它与用户的绑定，确定继续？'))return;try{await request(`/role/del_role?role_id=${id}`,{method:'DELETE'});toast('角色已删除。');$('#permissionEditor').classList.add('hidden');loadAdminRoles();}catch(error){showError(error);}}
async function adminSavePermissions(roleId){const permission_ids=$$('#permissionEditor input[type="checkbox"]:checked').map(input=>Number(input.value));try{await request('/role/assign_permissions',{method:'POST',body:JSON.stringify({role_id:Number(roleId),permission_ids})});toast('权限已保存。');}catch(error){showError(error);}}
async function adminCreateTeam(){const team_name=window.prompt('团队名称');if(!team_name)return;const team_code=window.prompt('团队编码');if(!team_code)return;const description=window.prompt('团队说明')||'';try{await request('/team/add_team',{method:'POST',body:JSON.stringify({team_name,team_code,description})});toast('团队已创建。');loadAdminTeams();loadAdminOverview();}catch(error){showError(error);}}
async function adminEditTeam(id){const team=state.admin.teams.find(item=>item.id===Number(id));if(!team)return;const team_name=window.prompt('团队名称',team.team_name);if(team_name===null)return;const description=window.prompt('团队说明',team.description||'');if(description===null)return;try{await request(`/team/update_team?team_id=${id}`,{method:'PUT',body:JSON.stringify({team_name,description})});toast('团队已更新。');loadAdminTeams();}catch(error){showError(error);}}
async function adminDeleteTeam(id){if(!window.confirm('删除团队会清理成员关系，确定继续？'))return;try{await request(`/team/del_team?team_id=${id}`,{method:'DELETE'});toast('团队已删除。');$('#adminTeamMembers').classList.add('hidden');loadAdminTeams();loadAdminOverview();}catch(error){showError(error);}}
async function adminShowMembers(id){const box=$('#adminTeamMembers');box.classList.remove('hidden');box.innerHTML='<div class="empty-loading">正在加载成员…</div>';try{const [members,userResult]=await Promise.all([request(`/team/query_members?team_id=${id}`),request('/user/query_users?username=&page=1&page_size=100')]);const memberIds=new Set(members.map(member=>Number(member.user_id)));const candidates=(userResult?.list||[]).filter(user=>!memberIds.has(Number(user.id)));box.innerHTML=`<div class="permission-editor-head"><div><span class="eyebrow">TEAM MEMBERS</span><h3>${escapeHtml(state.admin.teams.find(team=>team.id===Number(id))?.team_name||'团队')} · 成员</h3></div><button class="icon-button" data-close-members aria-label="关闭">×</button></div><div class="member-add-row"><select id="adminMemberSelect" aria-label="选择要加入团队的用户"><option value="">选择一个用户加入团队</option>${candidates.map(user=>`<option value="${user.id}">${escapeHtml(user.username)} · ${escapeHtml(user.email||'无邮箱')}</option>`).join('')}</select><button class="button button-primary" data-admin-add-member="${id}" ${candidates.length?'':'disabled'}>添加成员 <svg><use href="#i-plus"/></svg></button></div>${members.length?`<div class="member-list">${members.map(member=>`<div class="member-row"><span class="table-avatar">${escapeHtml(initials(member.username))}</span><div><strong>${escapeHtml(member.username)}</strong><small>${escapeHtml(member.email)}</small></div><button class="text-action danger" data-admin-remove-member="${member.user_id}" data-admin-team-id="${id}">移除</button></div>`).join('')}</div>`:'<div class="empty-state compact"><h3>暂无成员</h3><p>从上方选择用户，开始建立团队。</p></div>'}`}catch(error){box.innerHTML=`<div class="empty-state compact"><h3>成员加载失败</h3><p>${escapeHtml(error.message)}</p></div>`;}}
async function adminAddMember(teamId){const userId=Number($('#adminMemberSelect')?.value);if(!userId)return toast('先选择要加入团队的用户。');try{const result=await request('/team/add_member',{method:'POST',body:JSON.stringify({team_id:Number(teamId),user_id:userId})});toast(result?.msg||'成员已加入团队。');await adminShowMembers(teamId);loadAdminTeams();loadAdminUsers();}catch(error){showError(error);}}
async function adminRemoveMember(teamId,userId){if(!window.confirm('确定移除这个成员吗？'))return;try{await request(`/team/del_member?team_id=${teamId}&user_id=${userId}`,{method:'DELETE'});toast('成员已移除。');adminShowMembers(teamId);loadAdminTeams();}catch(error){showError(error);}}
function setSelectedFile(file){if(!file)return;$('#fileName').textContent=file.name;$('#uploadButton').disabled=false;$('#uploadStatus').textContent=`${(file.size/1024/1024).toFixed(2)} MB`}
function bindEvents(){ $('#authForm').addEventListener('submit',submitAuth); $('#authSwitch').addEventListener('click',()=>{state.authMode=state.authMode==='login'?'register':'login';updateAuthCopy()}); $('#logoutButton').addEventListener('click',()=>{state.token='';state.user=null;resetFitnessProfileSync();localStorage.removeItem('ironflow_token');localStorage.removeItem('ironflow_refresh_token');localStorage.removeItem('ironflow_user');showAuth();}); $('#saveApiBase').addEventListener('click',()=>{const value=$('#apiBase').value.trim().replace(/\/$/,'');if(!/^https?:\/\//.test(value)){toast('API 地址需要以 http:// 或 https:// 开头。');return}state.apiBase=value;localStorage.setItem('ironflow_api_base',value);updateUserUI();checkApi();toast('后端地址已保存。')}); $('#apiBase').value=state.apiBase; $$('.nav-item').forEach(item=>item.addEventListener('click',()=>navigate(item.dataset.page))); $$('.main-column').forEach(node=>node.addEventListener('click',event=>{const go=event.target.closest('[data-go]')?.dataset.go;if(go)navigate(go);const prompt=event.target.closest('[data-prompt]')?.dataset.prompt;if(prompt){$('#chatInput').value=prompt;sendChat(new Event('submit'))}const openUpload=event.target.closest('[data-open-upload]');if(openUpload)$('#uploadPanel').classList.remove('hidden');const publish=event.target.closest('[data-publish-doc]')?.dataset.publishDoc;if(publish)publishDocument(publish);const view=event.target.closest('[data-view-doc]')?.dataset.viewDoc;if(view)loadDocDetail(view);const deleteDoc=event.target.closest('[data-delete-doc]')?.dataset.deleteDoc;if(deleteDoc)deleteDocument(deleteDoc)})); $('#newChatButton').addEventListener('click',()=>createSession()); $('#clearChatButton').addEventListener('click',()=>createSession()); $('#chatForm').addEventListener('submit',sendChat); $('#chatInput').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendChat(event)}}); $('#chatInput').addEventListener('input',event=>{event.target.style.height='auto';event.target.style.height=`${Math.min(event.target.scrollHeight,115)}px`}); $('#sessionList').addEventListener('click',event=>{const del=event.target.closest('[data-delete-session]');if(del){event.stopPropagation();deleteSession(Number(del.dataset.deleteSession));return}const item=event.target.closest('[data-session-id]');if(item){state.activeSessionId=Number(item.dataset.sessionId);renderSessions();if(state.chatMessages[state.activeSessionId])renderChat(state.activeSessionId);else renderWelcome();loadSessionMessages(state.activeSessionId).catch(showError)}}); $('#searchForm').addEventListener('submit',event=>{event.preventDefault();loadDocuments($('#searchInput').value.trim())}); $('#uploadTrigger').addEventListener('click',()=>$('#uploadPanel').classList.toggle('hidden')); $('#closeUpload').addEventListener('click',()=>$('#uploadPanel').classList.add('hidden')); $('#fileInput').addEventListener('change',event=>setSelectedFile(event.target.files[0])); $('#uploadButton').addEventListener('click',uploadFile); $('#dropZone').addEventListener('dragover',event=>{event.preventDefault();$('#dropZone').classList.add('dragover')}); $('#dropZone').addEventListener('dragleave',()=>$('#dropZone').classList.remove('dragover')); $('#dropZone').addEventListener('drop',event=>{event.preventDefault();$('#dropZone').classList.remove('dragover');const file=event.dataTransfer.files[0];if(file){const dt=new DataTransfer();dt.items.add(file);$('#fileInput').files=dt.files;setSelectedFile(file)}}); $('#profileForm').addEventListener('submit',saveProfile); $('#mobileMenu').addEventListener('click',toggleMobileMenu); $('#mobileOverlay').addEventListener('click',closeMobileMenu); $('#userChip').addEventListener('click',()=>navigate('profile')); window.addEventListener('hashchange',()=>navigate(location.hash.slice(1),false)); }
function bindAdminEvents(){
  $$('.admin-tab').forEach(button=>button.addEventListener('click',()=>adminSetTab(button.dataset.adminTab)));
  $('#adminUserSearch').addEventListener('submit',event=>{event.preventDefault();state.admin.userKeyword=$('#adminUserKeyword').value.trim();state.admin.usersPage=1;loadAdminUsers();});
  $('#reviewStatusTabs').addEventListener('click',event=>{const button=event.target.closest('[data-review-status]');if(!button)return;state.admin.reviewStatus=button.dataset.reviewStatus;state.admin.reviewsPage=1;$$('#reviewStatusTabs button').forEach(item=>item.classList.toggle('active',item===button));loadAdminReviews();});
  $('#adminCreateUser').addEventListener('click',adminCreateUser);$('#adminCreateRole').addEventListener('click',adminCreateRole);$('#adminCreateTeam').addEventListener('click',adminCreateTeam);$('#adminRefreshSystem').addEventListener('click',loadAdminSystem);
  $('#adminWorkspace').addEventListener('click',event=>{const jump=event.target.closest('[data-admin-jump]');if(jump)return adminSetTab(jump.dataset.adminJump);const editUser=event.target.closest('[data-admin-edit-user]');if(editUser)return adminEditUser(editUser.dataset.adminEditUser);const roles=event.target.closest('[data-admin-user-roles]');if(roles)return adminAssignRoles(roles.dataset.adminUserRoles,roles.dataset.adminUserName,roles);const delUser=event.target.closest('[data-admin-delete-user]');if(delUser)return adminDeleteUser(delUser.dataset.adminDeleteUser);const review=event.target.closest('[data-review-action]');if(review)return adminReviewAction(review.dataset.reviewId,review.dataset.reviewAction==='approve'?1:2);const permissions=event.target.closest('[data-admin-permissions]');if(permissions)return loadAdminPermissions(permissions.dataset.adminPermissions);const editRole=event.target.closest('[data-admin-edit-role]');if(editRole)return adminEditRole(editRole.dataset.adminEditRole);const delRole=event.target.closest('[data-admin-delete-role]');if(delRole)return adminDeleteRole(delRole.dataset.adminDeleteRole);const savePermissions=event.target.closest('[data-save-permissions]');if(savePermissions)return adminSavePermissions(savePermissions.dataset.savePermissions);if(event.target.closest('[data-close-permissions]'))return $('#permissionEditor').classList.add('hidden');const members=event.target.closest('[data-admin-members]');if(members)return adminShowMembers(members.dataset.adminMembers);const editTeam=event.target.closest('[data-admin-edit-team]');if(editTeam)return adminEditTeam(editTeam.dataset.adminEditTeam);const delTeam=event.target.closest('[data-admin-delete-team]');if(delTeam)return adminDeleteTeam(delTeam.dataset.adminDeleteTeam);const addMember=event.target.closest('[data-admin-add-member]');if(addMember)return adminAddMember(addMember.dataset.adminAddMember);if(event.target.closest('[data-close-members]'))return $('#adminTeamMembers').classList.add('hidden');const removeMember=event.target.closest('[data-admin-remove-member]');if(removeMember)return adminRemoveMember(removeMember.dataset.adminTeamId,removeMember.dataset.adminRemoveMember);});
}
function bindChatDraftEvents() {
  const input=$('#chatInput');
  input.addEventListener('input',saveActiveChatDraft);
  const sessionList=$('#sessionList');
  sessionList.addEventListener('click',event=>{
    if(event.target.closest('[data-delete-session]'))return;
    if(event.target.closest('[data-session-id]'))saveActiveChatDraft();
  },true);
  sessionList.addEventListener('click',event=>{
    if(event.target.closest('[data-delete-session]'))return;
    const item=event.target.closest('[data-session-id]');
    if(item)restoreChatDraft(Number(item.dataset.sessionId));
  });
}
function bindSessionHistoryEvents() { const note=$('.composer-bottom span'); if(note) note.textContent='消息会保存到当前会话；AI 会参考本次会话历史，建议仅供参考。'; }
function bindTrainingEvents(){
  $('#trainingGenerateForm').addEventListener('submit', generateTrainingPlan);
  $('#trainingEquipment').addEventListener('input', () => TrainingProfilePrefill.markTrainingProfileFieldTouched(state.trainingProfilePrefill, 'equipment'));
  $('#trainingDays').addEventListener('input', () => TrainingProfilePrefill.markTrainingProfileFieldTouched(state.trainingProfilePrefill, 'trainingDays'));
  $('#trainingLimitations').addEventListener('input', () => TrainingProfilePrefill.markTrainingProfileFieldTouched(state.trainingProfilePrefill, 'limitations'));
  $('#trainingPreview').addEventListener('click', event => { const save = event.target.closest('#saveTrainingPlan'); if (save) return saveTrainingPreview(); const resume = event.target.closest('[data-resume-workout]'); if (resume) return resumeWorkout(resume.dataset.resumeWorkout); const start = event.target.closest('[data-start-workout]'); if (start) startWorkout(start.dataset.startWorkout, start.dataset.startWorkoutDay); });
  $('#trainingSavedPlans').addEventListener('click', event => { const item=event.target.closest('[data-training-plan-id]'); if(item)openSavedTrainingPlan(Number(item.dataset.trainingPlanId)); });
  $('#trainingWorkoutPanel').addEventListener('submit', completeActiveWorkout);
  $('#trainingWorkoutPanel').addEventListener('click', event => { if (event.target.closest('[data-close-workout]')) return renderWorkoutPanel(null); const cancel = event.target.closest('[data-cancel-workout]'); if (cancel) cancelWorkout(cancel.dataset.cancelWorkout); });
  $('#trainingWorkoutHistory').addEventListener('click', event => { const resume=event.target.closest('[data-resume-workout]'); if(resume)return resumeWorkout(resume.dataset.resumeWorkout); const cancel=event.target.closest('[data-cancel-workout]'); if(cancel)return cancelWorkout(cancel.dataset.cancelWorkout); const del=event.target.closest('[data-delete-workout]'); if(del)return deleteWorkout(del.dataset.deleteWorkout); });
}
function boot(){restoreChatMessages();bindEvents();bindChatDraftEvents();bindAdminEvents();bindTrainingEvents();bindNutritionEvents();bindSessionHistoryEvents();updateAuthCopy();if(state.token&&state.user)showApp();else showAuth();}
boot();

