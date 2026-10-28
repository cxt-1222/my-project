const assert = require('node:assert/strict');
const test = require('node:test');

const { isTrainingPlanIntent } = require('../frontend/intent-routing.js');

test('recognizes an explicit Chinese training-plan request', () => {
  assert.equal(isTrainingPlanIntent('我想增肌，刚开始训练，帮我安排一周计划。'), true);
  assert.equal(isTrainingPlanIntent('帮我安排一周的增肌计划。'), true);
  assert.equal(isTrainingPlanIntent('我想要一个健身计划。'), true);
  assert.equal(isTrainingPlanIntent('请生成一个只包含一天的训练计划。'), true);
});

test('recognizes an explicit English workout-plan request', () => {
  assert.equal(isTrainingPlanIntent('Create a 3-day workout plan to build muscle.'), true);
  assert.equal(isTrainingPlanIntent('I want a workout plan.'), true);
});

test('leaves knowledge questions in the existing AI chat flow', () => {
  assert.equal(isTrainingPlanIntent('深蹲主要锻炼哪些肌群？'), false);
  assert.equal(isTrainingPlanIntent('新手一周练几次比较合适？'), false);
  assert.equal(isTrainingPlanIntent('训练计划里深蹲时膝盖疼怎么办？'), false);
});

test('handles empty or non-string input safely', () => {
  assert.equal(isTrainingPlanIntent(''), false);
  assert.equal(isTrainingPlanIntent(null), false);
});
