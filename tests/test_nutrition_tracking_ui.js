const assert = require('node:assert/strict');
const test = require('node:test');

const nutrition = require('../frontend/nutrition-tracking.js');

const baseFields = {
  meal_type: 'breakfast',
  food_name: ' 燕麦粥 ',
  amount: '250',
  unit: 'ml',
  calories_kcal: '160.5',
  protein_g: '6.2',
  carbohydrate_g: '28',
  fat_g: '3.1',
};

test('local date helper uses local calendar components instead of UTC conversion', () => {
  const localDate = new Date(2026, 9, 22, 0, 5);
  assert.equal(nutrition.todayLocalDate(localDate), '2026-10-22');
  assert.equal(nutrition.isCalendarDate('2026-10-22'), true);
  assert.equal(nutrition.isCalendarDate('2026-02-30'), false);
});

test('nutrition payload trims text and sends the selected date with numeric values', () => {
  assert.deepEqual(nutrition.buildNutritionPayload(baseFields, '2026-10-22'), {
    date: '2026-10-22',
    meal_type: 'breakfast',
    food_name: '燕麦粥',
    amount: 250,
    unit: 'ml',
    calories_kcal: 160.5,
    protein_g: 6.2,
    carbohydrate_g: 28,
    fat_g: 3.1,
  });
});

test('nutrition form payload rejects missing, negative, invalid category, and invalid date values', () => {
  for (const [fields, date] of [
    [{...baseFields, food_name: '  '}, '2026-10-22'],
    [{...baseFields, amount: '0'}, '2026-10-22'],
    [{...baseFields, protein_g: '-1'}, '2026-10-22'],
    [{...baseFields, meal_type: 'midnight'}, '2026-10-22'],
    [baseFields, 'not-a-date'],
    [baseFields, '2026-02-30'],
  ]) {
    assert.throws(() => nutrition.buildNutritionPayload(fields, date));
  }
});

test('photo confirmation payload validates all reviewed food items and uses the selected date', () => {
  const payload = nutrition.buildPhotoConfirmPayload([{
    ...baseFields,
    meal_type: 'lunch',
    food_name: '鸡胸肉',
    amount: '150',
    unit: 'g',
    calories_kcal: '248',
    protein_g: '46.5',
    carbohydrate_g: '0',
    fat_g: '5.4',
  }], '2026-10-23');
  assert.deepEqual(payload, {
    date: '2026-10-23',
    items: [{
      meal_type: 'lunch', food_name: '鸡胸肉', amount: 150, unit: 'g',
      calories_kcal: 248, protein_g: 46.5, carbohydrate_g: 0, fat_g: 5.4,
    }],
  });
  assert.throws(() => nutrition.buildPhotoConfirmPayload([], '2026-10-23'));
  assert.throws(() => nutrition.buildPhotoConfirmPayload([baseFields], '2026-02-30'));
});

test('photo preview escapes model-provided fields and shows confirmation is explicit', () => {
  const html = nutrition.renderPhotoPreview({
    id: 9,
    status: 'preview',
    image_url: '/nutrition/photos/9/image',
    items: [{...baseFields, food_name: '<img src=x onerror=alert(1)>'}],
  }, value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[char])));
  assert.match(html, /估算结果/);
  assert.match(html, /确认并保存/);
  assert.match(html, /&lt;img/);
  assert.doesNotMatch(html, /<img src=x/);
  assert.match(html, /data-remove-photo-item="0"/);
  assert.match(html, /class="nutrition-photo-image"[^>]*hidden/);
  assert.doesNotMatch(html, /src="\/nutrition\/photos\/9\/image/);
});

test('daily cards render server totals and record list escapes user-controlled text', () => {
  const totals = nutrition.renderDailySummary({totals:{calories_kcal:1234.5,protein_g:60,carbohydrate_g:130,fat_g:40}}, value => String(value));
  assert.match(totals, /1,234\.5/);
  assert.match(totals, /当日记录合计/);
  const records = nutrition.renderNutritionRecords([{
    id: 12,
    meal_type: 'lunch',
    food_name: '<img src=x onerror=alert(1)>',
    amount: 120,
    unit: 'g',
    calories_kcal: 200,
    protein_g: 12,
    carbohydrate_g: 20,
    fat_g: 8,
  }], value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[char])));
  assert.match(records, /&lt;img/);
  assert.doesNotMatch(records, /<img/);
  assert.match(records, /data-edit-nutrition="12"/);
});

test('empty nutrition records show an explicit no-data state', () => {
  assert.match(nutrition.renderNutritionRecords([]), /还没有饮食记录/);
});

test('approved food catalog prefill uses per-100g values without saving', () => {
  const draft = nutrition.buildCatalogDraft({
    id: 5,
    name: '燕麦',
    source: {
      dataset: 'approved-food',
      revision: 'abcdef1234567890',
      source_record_id: 'oats-1',
    },
    nutrition: {
      per_100g: {
        calories_kcal: 389,
        protein_g: 16.9,
        carbohydrate_g: 66.3,
        fat_g: 6.9,
        complete: true,
      },
    },
  }, 'food');
  assert.equal(draft.fields.food_name, '燕麦');
  assert.equal(draft.fields.amount, 100);
  assert.equal(draft.fields.unit, 'g');
  assert.equal(draft.fields.protein_g, 16.9);
  assert.equal(draft.basisLabel, '每 100 克');
  assert.match(draft.sourceLabel, /approved-food/);
  assert.match(draft.sourceLabel, /oats-1/);
});

test('recipe catalog prefill uses per-serving values and keeps missing nutrition editable', () => {
  const draft = nutrition.buildCatalogDraft({
    id: 7,
    title: '燕麦碗',
    source_name: 'Example recipes',
    source: {dataset: 'approved-recipes', revision: '1234567890abcdef', source_record_id: 'bowl-1'},
    nutrition: {
      per_serving: {
        calories_kcal: null,
        protein_g: 8.5,
        carbohydrate_g: null,
        fat_g: null,
        complete: false,
      },
      missing_ingredients: [{name: '牛奶', reason: '关联食材未获准或已停用'}],
    },
  }, 'recipe');
  assert.equal(draft.fields.amount, 1);
  assert.equal(draft.fields.unit, '份');
  assert.equal(draft.fields.calories_kcal, '');
  assert.equal(draft.fields.protein_g, 8.5);
  assert.equal(draft.complete, false);
  assert.match(draft.missingIngredients[0].reason, /未获准/);
});

test('catalog result and selection markup show source, basis and one explicit selection', () => {
  const escape = value => String(value).replace(/[&<>"']/g, char => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;',
  }[char]));
  const item = {
    id: 5,
    name: '<img src=x>',
    source: {dataset:'safe', revision:'abc', source_record_id:'food-1'},
    nutrition: {per_100g:{
      calories_kcal: 100, protein_g: 10, carbohydrate_g: 0, fat_g: 2, complete:true,
    }},
  };
  const results = nutrition.renderCatalogResults([item], 'food', escape);
  assert.match(results, /预填到饮食草稿/);
  assert.match(results, /每 100 克/);
  assert.match(results, /safe/);
  assert.doesNotMatch(results, /<img src=x>/);

  const draft = nutrition.buildCatalogDraft(item, 'food');
  const selection = nutrition.renderCatalogSelection(draft, escape);
  assert.match(selection, /本次已选择 1 项/);
  assert.match(selection, /草稿尚未保存/);
  assert.match(selection, /取消预填/);
});
