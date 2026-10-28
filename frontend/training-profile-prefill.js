(function (root) {
  const fields = ['equipment', 'trainingDays', 'limitations'];

  function createTrainingProfilePrefillState() {
    return { owner: null, touched: Object.fromEntries(fields.map(field => [field, false])) };
  }

  function normalizeValues(values = {}) {
    return Object.fromEntries(fields.map(field => [field, String(values[field] || '')]));
  }

  function prepareTrainingProfileOwner(state, owner, currentValues = {}) {
    const ownerKey = owner == null ? null : String(owner);
    const values = normalizeValues(currentValues);
    if (state.owner === ownerKey) return values;

    if (state.owner !== null) {
      for (const field of fields) values[field] = '';
      state.touched = Object.fromEntries(fields.map(field => [field, false]));
    } else {
      for (const field of fields) state.touched[field] = Boolean(values[field].trim());
    }
    state.owner = ownerKey;
    return values;
  }

  function applyTrainingProfilePrefill(state, profile, currentValues = {}) {
    const values = normalizeValues(currentValues);
    const profileValues = {
      equipment: String(profile?.equipment || ''),
      trainingDays: profile?.weekly_training_days == null ? '' : String(profile.weekly_training_days),
      limitations: String(profile?.limitations || ''),
    };
    for (const field of fields) {
      if (!state.touched[field]) values[field] = profileValues[field];
    }
    return values;
  }

  function markTrainingProfileFieldTouched(state, field) {
    if (Object.prototype.hasOwnProperty.call(state.touched, field)) state.touched[field] = true;
  }

  function resetTrainingProfilePrefillState(state) {
    state.owner = null;
    state.touched = Object.fromEntries(fields.map(field => [field, false]));
    return normalizeValues();
  }

  const api = {
    createTrainingProfilePrefillState,
    prepareTrainingProfileOwner,
    applyTrainingProfilePrefill,
    markTrainingProfileFieldTouched,
    resetTrainingProfilePrefillState,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.TrainingProfilePrefill = api;
}(globalThis));
