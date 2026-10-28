(function (root) {
  const planTerms = /(训练计划|健身计划|锻炼计划|运动计划|训练方案|健身方案|一周计划|(?:增肌|减脂|体能|力量).{0,6}(?:计划|方案)|workout\s+(?:plan|program)|training\s+(?:plan|program))/i;
  const fitnessTerms = /(训练|健身|锻炼|运动|增肌|减脂|体能|力量|肌肉|胸|背|腿|肩|腹肌|核心|workout|training|fitness|muscle|weight\s*loss|exercise)/i;
  const creationActions = /(制定|安排|生成|设计|规划|编排|拟定|创建|想要|需要|做(?=.{0,10}(?:一份|一个|一套|计划|方案))|create|make|build|design|generate|draft|want\s+(?:a|an|my)?|need\s+(?:a|an|my)?)/i;

  function isTrainingPlanIntent(text) {
    const query = String(text || '').trim();
    return Boolean(query && planTerms.test(query) && fitnessTerms.test(query) && creationActions.test(query));
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { isTrainingPlanIntent };
  } else {
    root.isTrainingPlanIntent = isTrainingPlanIntent;
  }
})(globalThis);
