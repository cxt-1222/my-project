(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.TrainingWorkoutUI = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const escapeHtml = value => String(value ?? '').replace(/[&<>\'"]/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#039;', '"': '&quot;',
  }[char]));

  function plannedRepDefault(value) {
    const match = String(value ?? '').match(/\d+/);
    return match ? Math.max(1, Number(match[0])) : 1;
  }

  function buildCompletionPayload(record, getValue, bodyWeightValue) {
    const exercises = (record?.exercises || []).map((exercise, index) => {
      const value = field => getValue(field, index);
      const weight = String(value('weight_kg') ?? '').trim();
      return {
        name: exercise.name,
        sets: Number(value('sets')),
        reps: Number(value('reps')),
        weight_kg: weight === '' ? null : Number(weight),
      };
    });
    const bodyWeight = String(bodyWeightValue ?? '').trim();
    return {
      exercises,
      body_weight_kg: bodyWeight === '' ? null : Number(bodyWeight),
    };
  }

  async function fetchDashboardTrainingData(request) {
    const [stats, workouts] = await Promise.all([
      request('/training/stats'),
      request('/training/workouts?limit=5&offset=0'),
    ]);
    return {stats, workouts};
  }

  async function fetchWorkoutHistoryData(request) {
    const [workouts, stats] = await Promise.all([
      request('/training/workouts?limit=50&offset=0'),
      request('/training/stats'),
    ]);
    return {workouts, stats};
  }

  function formatDuration(seconds) {
    const totalMinutes = Math.max(0, Math.floor(Number(seconds || 0) / 60));
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    return hours ? `${hours} 小时 ${minutes} 分钟` : `${minutes} 分钟`;
  }

  function renderStats(stats) {
    if (!stats) return '<div class="empty-state compact"><h3>训练统计暂不可用</h3><p>请稍后刷新，或确认训练记录数据库迁移已执行。</p></div>';
    const weightChange = stats.body_weight_change_kg == null
      ? '记录两次后显示'
      : `${Number(stats.body_weight_change_kg) > 0 ? '+' : ''}${Number(stats.body_weight_change_kg).toFixed(1)} kg`;
    const values = [
      ['本周训练', `${Number(stats.week_workouts_count || 0)} 次`, '已完成训练'],
      ['连续打卡', `${Number(stats.streak_days || 0)} 天`, '按连续训练日期计算'],
      ['本周时长', formatDuration(stats.week_duration_seconds), '已完成训练总时长'],
      ['本周训练容量', `${Number(stats.week_volume_kg || 0).toLocaleString('zh-CN')} kg`, '仅统计填写了重量的动作'],
      ['本周重点', stats.primary_focus || '暂无数据', '出现最多的训练重点'],
      ['累计体重变化', weightChange, stats.latest_body_weight_kg == null ? '完成训练时可选填写' : `较首次记录 · 最近 ${Number(stats.latest_body_weight_kg).toFixed(1)} kg`],
    ];
    return values.map(([label, value, note]) => `<article class="training-stat-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note)}</small></article>`).join('');
  }

  function recordVolume(record) {
    return (record.exercises || []).reduce((total, exercise) => {
      if (exercise.weight_kg == null) return total;
      return total + Number(exercise.sets || 0) * Number(exercise.reps || 0) * Number(exercise.weight_kg || 0);
    }, 0);
  }

  function renderHistory(records, {compact = false} = {}) {
    if (!records?.length) {
      return `<div class="empty-state compact"><h3>还没有训练记录</h3><p>从已保存的训练计划选择训练日，开始记录第一次训练。</p>${compact ? '<button class="text-action" data-go="training">打开训练计划</button>' : ''}</div>`;
    }
    return records.map(record => {
      const inProgress = record.status === 'in_progress';
      const started = record.started_at ? new Date(record.started_at).toLocaleString('zh-CN', {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit'}) : '时间未知';
      const duration = record.duration_seconds == null ? '进行中' : formatDuration(record.duration_seconds);
      const volume = record.status === 'completed' ? recordVolume(record) : 0;
      const exerciseDetails = record.status === 'completed' && record.exercises?.length
        ? `<details class="workout-history-exercises"><summary>查看动作完成情况</summary><ul>${record.exercises.map(exercise => `<li><strong>${escapeHtml(exercise.name)}</strong><span>${Number(exercise.sets || 0)} 组 × ${Number(exercise.reps || 0)} 次${exercise.weight_kg == null ? ' · 未记录重量' : ` · ${Number(exercise.weight_kg)} kg`}</span></li>`).join('')}</ul></details>`
        : '';
      const actions = compact ? '' : inProgress
        ? `<div class="workout-history-actions"><button class="text-action" data-resume-workout="${Number(record.id)}">继续训练</button><button class="text-action danger" data-cancel-workout="${Number(record.id)}">取消</button></div>`
        : `<div class="workout-history-actions"><button class="text-action danger" data-delete-workout="${Number(record.id)}">删除记录</button></div>`;
      return `<article class="workout-history-item ${inProgress ? 'is-in-progress' : ''}"><div class="workout-history-main"><div><strong>${escapeHtml(record.plan_title || '训练记录')} · ${escapeHtml(record.plan_day || '')}</strong><small>${escapeHtml(started)} · ${escapeHtml(record.focus || '训练')} · ${escapeHtml(duration)}</small></div><span class="workout-status-chip ${inProgress ? 'is-active' : ''}">${inProgress ? '进行中' : '已完成'}</span></div>${record.status === 'completed' ? `<p class="workout-history-detail">${(record.exercises || []).length} 个动作 · 训练容量 ${volume.toLocaleString('zh-CN')} kg${record.body_weight_kg == null ? '' : ` · 体重 ${Number(record.body_weight_kg).toFixed(1)} kg`}</p>${exerciseDetails}` : ''}${actions}</article>`;
    }).join('');
  }

  function wasPlanDayCompletedToday(records, planId, day, now = new Date()) {
    const dateInAppZone = value => new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    }).format(value);
    const localToday = dateInAppZone(now);
    return (records || []).some(record => {
      if (record.status !== 'completed' || Number(record.plan_id) !== Number(planId) || record.plan_day !== day || !record.completed_at) return false;
      return dateInAppZone(new Date(record.completed_at)) === localToday;
    });
  }

  function findInProgressPlanWorkoutToday(records, planId, day, now = new Date()) {
    const dateInAppZone = value => new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    }).format(value);
    const today = dateInAppZone(now);
    return (records || []).find(record => record.status === 'in_progress'
      && Number(record.plan_id) === Number(planId)
      && record.plan_day === day
      && record.started_at
      && dateInAppZone(new Date(record.started_at)) === today) || null;
  }

  return {
    plannedRepDefault,
    buildCompletionPayload,
    fetchDashboardTrainingData,
    fetchWorkoutHistoryData,
    formatDuration,
    renderStats,
    recordVolume,
    renderHistory,
    wasPlanDayCompletedToday,
    findInProgressPlanWorkoutToday,
  };
});
