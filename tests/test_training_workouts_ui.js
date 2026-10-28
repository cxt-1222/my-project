const assert = require('node:assert/strict');
const test = require('node:test');

const ui = require('../frontend/training-workouts.js');

test('planned rep ranges initialize to the lower bound without changing the plan text', () => {
  assert.equal(ui.plannedRepDefault('8-12'), 8);
  assert.equal(ui.plannedRepDefault('10'), 10);
  assert.equal(ui.plannedRepDefault('按能力完成'), 1);
});

test('completion form data includes actual work and converts optional weights safely', () => {
  const record = {exercises:[{name:'哑铃卧推'},{name:'俯卧撑'}]};
  const values = new Map([
    ['sets:0','4'], ['reps:0','10'], ['weight_kg:0','22.5'],
    ['sets:1','3'], ['reps:1','12'], ['weight_kg:1',''],
  ]);
  const payload = ui.buildCompletionPayload(record, (field, index) => values.get(`${field}:${index}`), ' 70.5 ');
  assert.deepEqual(payload, {
    exercises:[
      {name:'哑铃卧推',sets:4,reps:10,weight_kg:22.5},
      {name:'俯卧撑',sets:3,reps:12,weight_kg:null},
    ],
    body_weight_kg:70.5,
  });
  assert.equal(ui.buildCompletionPayload(record, () => '1', '').body_weight_kg, null);
});

test('dashboard and history refresh request their matching live data in parallel', async () => {
  const expected = {
    '/training/stats': {week_workouts_count:2},
    '/training/workouts?limit=5&offset=0': [{id:1}],
    '/training/workouts?limit=50&offset=0': [{id:2}],
  };
  const calls = [];
  const request = async path => { calls.push(path); return expected[path]; };

  const dashboard = await ui.fetchDashboardTrainingData(request);
  assert.deepEqual(dashboard, {stats:expected['/training/stats'],workouts:expected['/training/workouts?limit=5&offset=0']});
  assert.deepEqual(new Set(calls), new Set(['/training/stats','/training/workouts?limit=5&offset=0']));

  calls.length = 0;
  const history = await ui.fetchWorkoutHistoryData(request);
  assert.deepEqual(history, {stats:expected['/training/stats'],workouts:expected['/training/workouts?limit=50&offset=0']});
  assert.deepEqual(new Set(calls), new Set(['/training/stats','/training/workouts?limit=50&offset=0']));
});

test('stats show real values and clearly distinguish unavailable measurements', () => {
  const html = ui.renderStats({
    week_workouts_count: 3,
    streak_days: 2,
    week_duration_seconds: 5400,
    week_volume_kg: 12750,
    primary_focus: '<script>alert(1)</script>',
    latest_body_weight_kg: 70,
    body_weight_change_kg: null,
  });
  assert.match(html, /3 次/);
  assert.match(html, /1 小时 30 分钟/);
  assert.match(html, /12,750 kg/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /记录两次后显示/);
});

test('workout volume ignores unloaded exercises and history escapes user content', () => {
  assert.equal(ui.recordVolume({exercises:[
    {sets:3,reps:10,weight_kg:20},
    {sets:4,reps:12,weight_kg:null},
  ]}), 600);
  const html = ui.renderHistory([{
    id: 1,
    status: 'completed',
    plan_title: '<b>计划</b>',
    plan_day: '周一',
    started_at: '2026-10-22T01:00:00Z',
    completed_at: '2026-10-22T02:00:00Z',
    duration_seconds: 3600,
    focus: '上肢',
    exercises: [{sets:3,reps:10,weight_kg:20}],
  }]);
  assert.match(html, /&lt;b&gt;计划&lt;\/b&gt;/);
  assert.match(html, /训练容量 600 kg/);
  assert.match(html, /删除记录/);
});

test('plan-day completion is scoped to plan, day, status, and local calendar date', () => {
  const now = new Date('2026-10-22T10:00:00+08:00');
  const records = [
    {status:'completed',plan_id:3,plan_day:'周一',completed_at:'2026-10-22T01:00:00Z'},
    {status:'in_progress',plan_id:3,plan_day:'周二',started_at:'2026-10-22T01:30:00Z',completed_at:null},
  ];
  assert.equal(ui.wasPlanDayCompletedToday(records, 3, '周一', now), true);
  assert.equal(ui.wasPlanDayCompletedToday(records, 4, '周一', now), false);
  assert.equal(ui.wasPlanDayCompletedToday(records, 3, '周二', now), false);
  assert.equal(ui.findInProgressPlanWorkoutToday(records, 3, '周二', now), records[1]);
  assert.equal(ui.findInProgressPlanWorkoutToday(records, 3, '周一', now), null);
});
