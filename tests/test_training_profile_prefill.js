const assert = require('node:assert/strict');
const test = require('node:test');

const {
  createTrainingProfilePrefillState,
  prepareTrainingProfileOwner,
  applyTrainingProfilePrefill,
  markTrainingProfileFieldTouched,
} = require('../frontend/training-profile-prefill.js');

test('profile values are written into the training form fields', () => {
  const state = createTrainingProfilePrefillState();
  prepareTrainingProfileOwner(state, 1);

  const values = applyTrainingProfilePrefill(state, {
    equipment: '哑铃、弹力带',
    weekly_training_days: 3,
    limitations: '避免跳跃动作',
  });

  assert.deepEqual(values, {
    equipment: '哑铃、弹力带',
    trainingDays: '3',
    limitations: '避免跳跃动作',
  });
});

test('manual edits are retained when the profile is loaded again', () => {
  const state = createTrainingProfilePrefillState();
  prepareTrainingProfileOwner(state, 1);
  applyTrainingProfilePrefill(state, {
    equipment: '哑铃',
    weekly_training_days: 3,
    limitations: '避免跳跃动作',
  });
  markTrainingProfileFieldTouched(state, 'equipment');
  markTrainingProfileFieldTouched(state, 'limitations');

  const values = applyTrainingProfilePrefill(state, {
    equipment: '杠铃',
    weekly_training_days: 4,
    limitations: '避免深蹲',
  }, { equipment: '只用哑铃', trainingDays: '3', limitations: '膝盖不适' });

  assert.deepEqual(values, {
    equipment: '只用哑铃',
    trainingDays: '4',
    limitations: '膝盖不适',
  });
});

test('values typed while the profile request is in flight are not overwritten', () => {
  const state = createTrainingProfilePrefillState();
  const values = prepareTrainingProfileOwner(state, 1, {
    equipment: '',
    trainingDays: '',
    limitations: '',
  });
  markTrainingProfileFieldTouched(state, 'equipment');

  const filled = applyTrainingProfilePrefill(state, {
    equipment: '哑铃',
    weekly_training_days: 3,
    limitations: '避免跳跃动作',
  }, { ...values, equipment: '仅弹力带' });

  assert.deepEqual(filled, {
    equipment: '仅弹力带',
    trainingDays: '3',
    limitations: '避免跳跃动作',
  });
});

test('switching accounts clears the previous account values before applying the new profile', () => {
  const state = createTrainingProfilePrefillState();
  prepareTrainingProfileOwner(state, 1);
  applyTrainingProfilePrefill(state, {
    equipment: '哑铃',
    weekly_training_days: 3,
    limitations: '账号 A 的限制',
  });
  markTrainingProfileFieldTouched(state, 'equipment');

  const values = prepareTrainingProfileOwner(state, 2, {
    equipment: '账号 A 手动改过的器械',
    trainingDays: '3',
    limitations: '账号 A 的限制',
  });
  const filled = applyTrainingProfilePrefill(state, {
    equipment: '杠铃',
    weekly_training_days: 5,
    limitations: '账号 B 的限制',
  }, values);

  assert.deepEqual(filled, { equipment: '杠铃', trainingDays: '5', limitations: '账号 B 的限制' });
});
