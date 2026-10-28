(function (root) {
  const MEAL_LABELS = {
    breakfast: '早餐',
    lunch: '午餐',
    dinner: '晚餐',
    snack: '加餐',
  };
  const NUTRIENT_FIELDS = [
    ['calories_kcal', '热量', 'kcal'],
    ['protein_g', '蛋白质', 'g'],
    ['carbohydrate_g', '碳水化合物', 'g'],
    ['fat_g', '脂肪', 'g'],
  ];

  function todayLocalDate(now = new Date()) {
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  function numericField(value, label, {positive = false} = {}) {
    if (value == null || String(value).trim() === '') throw new Error(`请填写${label}。`);
    const number = Number(value);
    if (!Number.isFinite(number) || (positive ? number <= 0 : number < 0)) {
      throw new Error(`${label}必须是${positive ? '大于 0' : '不小于 0'}的有效数字。`);
    }
    return number;
  }

  function isCalendarDate(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
    if (!match) return false;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const parsed = new Date(year, month - 1, day);
    return parsed.getFullYear() === year && parsed.getMonth() === month - 1 && parsed.getDate() === day;
  }

  function buildNutritionPayload(fields, date) {
    const foodName = String(fields.food_name || '').trim();
    const unit = String(fields.unit || '').trim();
    if (!isCalendarDate(date)) throw new Error('请选择有效的饮食日期。');
    if (!foodName || foodName.length > 120) throw new Error('食物名称不能为空，且不超过 120 个字符。');
    if (!Object.hasOwn(MEAL_LABELS, fields.meal_type)) throw new Error('请选择有效餐次。');
    if (!unit || unit.length > 20) throw new Error('份量单位不能为空，且不超过 20 个字符。');
    return {
      date,
      meal_type: fields.meal_type,
      food_name: foodName,
      amount: numericField(fields.amount, '份量', {positive: true}),
      unit,
      calories_kcal: numericField(fields.calories_kcal, '热量'),
      protein_g: numericField(fields.protein_g, '蛋白质'),
      carbohydrate_g: numericField(fields.carbohydrate_g, '碳水化合物'),
      fat_g: numericField(fields.fat_g, '脂肪'),
    };
  }

  function safeNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : 0;
  }

  function formatAmount(value, maximumFractionDigits = 2) {
    return safeNumber(value).toLocaleString('zh-CN', {maximumFractionDigits});
  }

  function renderDailySummary(summary = {}, escapeHtml = value => String(value)) {
    const totals = summary?.totals || {};
    const cards = [
      ['总热量', totals.calories_kcal, 'kcal', 'nutrition-total-calories'],
      ['蛋白质', totals.protein_g, 'g', 'nutrition-total-protein'],
      ['碳水化合物', totals.carbohydrate_g, 'g', 'nutrition-total-carbs'],
      ['脂肪', totals.fat_g, 'g', 'nutrition-total-fat'],
    ];
    return cards.map(([label, value, unit, className]) => `
      <article class="nutrition-total-card ${className}">
        <span>${label}</span>
        <strong>${escapeHtml(formatAmount(value))}<small>${unit}</small></strong>
        <small>当日记录合计</small>
      </article>`).join('');
  }

  function renderNutritionRecords(records = [], escapeHtml = value => String(value)) {
    if (!records.length) {
      return '<div class="empty-state compact"><div><h3>这一天还没有饮食记录</h3><p>从左侧填写食物和营养值，保存后会显示在这里。</p></div></div>';
    }
    return records.map(record => {
      const id = Number(record.id);
      const meal = MEAL_LABELS[record.meal_type] || '餐次';
      return `<article class="nutrition-record" data-nutrition-id="${Number.isSafeInteger(id) && id > 0 ? id : 0}">
        <div class="nutrition-record-main">
          <div class="nutrition-record-heading"><span class="nutrition-meal-chip">${meal}</span><strong>${escapeHtml(record.food_name)}</strong></div>
          <p>份量 ${escapeHtml(formatAmount(record.amount, 3))} ${escapeHtml(record.unit)}${record.source === 'photo' ? ' · 图片识别后确认' : ''}</p>
          <small>${escapeHtml(formatAmount(record.calories_kcal))} kcal · 蛋白质 ${escapeHtml(formatAmount(record.protein_g))} g · 碳水 ${escapeHtml(formatAmount(record.carbohydrate_g))} g · 脂肪 ${escapeHtml(formatAmount(record.fat_g))} g</small>
        </div>
        <div class="nutrition-record-actions">
          <button class="text-action" type="button" data-edit-nutrition="${Number.isSafeInteger(id) && id > 0 ? id : 0}" ${id > 0 ? '' : 'disabled'}>编辑</button>
          <button class="text-action danger" type="button" data-delete-nutrition="${Number.isSafeInteger(id) && id > 0 ? id : 0}" ${id > 0 ? '' : 'disabled'}>删除</button>
        </div>
      </article>`;
    }).join('');
  }

  function buildPhotoConfirmPayload(items, date) {
    if (!Array.isArray(items) || items.length < 1 || items.length > 20) {
      throw new Error('请保留 1 至 20 项食物后再确认。');
    }
    const normalized = items.map(item => {
      const payload = buildNutritionPayload(item, date);
      const {date: _date, ...food} = payload;
      return food;
    });
    return {date, items: normalized};
  }

  function renderPhotoPreview(preview, escapeHtml = value => String(value)) {
    if (!preview || !Array.isArray(preview.items)) return '';
    const id = Number(preview.id);
    const image = preview.image_url
      ? '<img class="nutrition-photo-image" alt="本次餐食图片预览" hidden>'
      : '';
    const items = preview.items.map((item, index) => `
      <fieldset class="nutrition-photo-food" data-photo-item-index="${index}">
        <legend>食物 ${index + 1}</legend>
        <label>餐次<select data-photo-field="meal_type" required>${Object.entries(MEAL_LABELS).map(([value, label]) => `<option value="${value}" ${value === item.meal_type ? 'selected' : ''}>${label}</option>`).join('')}</select></label>
        <label>食物名称<input data-photo-field="food_name" maxlength="120" required value="${escapeHtml(item.food_name || '')}"></label>
        <div class="nutrition-photo-amount-row">
          <label>份量<input data-photo-field="amount" type="number" min="0.001" step="0.001" required value="${escapeHtml(item.amount ?? '')}"></label>
          <label>单位<input data-photo-field="unit" maxlength="20" required value="${escapeHtml(item.unit || 'g')}"></label>
        </div>
        <div class="nutrition-photo-nutrients">${NUTRIENT_FIELDS.map(([field, label, unit]) => `<label>${label} <span>${unit}</span><input data-photo-field="${field}" type="number" min="0" step="0.01" required value="${escapeHtml(item[field] ?? '')}"></label>`).join('')}</div>
        <button type="button" class="text-action danger" data-remove-photo-item="${index}" aria-label="移除食物 ${index + 1}">移除</button>
      </fieldset>`).join('');
    const confirmed = preview.status === 'confirmed';
    return `<div class="nutrition-photo-preview" data-preview-id="${Number.isSafeInteger(id) && id > 0 ? id : 0}">
      <div class="nutrition-photo-preview-header"><div><strong>识别预览</strong><span>估算结果 · ${confirmed ? '已确认保存' : '请核对并修改'}</span></div>${image}</div>
      <div class="nutrition-photo-food-list">${items || '<p class="muted">没有食物项目，请重新识别图片。</p>'}</div>
      ${confirmed ? '<p class="nutrition-photo-state" role="status">该预览已保存为营养记录，不能重复确认。</p>' : `<div class="nutrition-photo-actions"><button type="button" class="button button-light" data-add-photo-item>添加食物</button><button type="button" class="button button-primary" data-confirm-photo="${id}" ${id > 0 ? '' : 'disabled'}>确认并保存</button><button type="button" class="text-action danger" data-cancel-photo="${id}">取消本次识别</button></div>`}
      <p class="nutrition-photo-error" role="alert"></p>
    </div>`;
  }

  function photoPreviewStorageKey(userId) {
    return `ironflow_nutrition_photo_preview_${encodeURIComponent(String(userId || ''))}`;
  }

  const api = {todayLocalDate, isCalendarDate, buildNutritionPayload, buildPhotoConfirmPayload, renderDailySummary, renderNutritionRecords, renderPhotoPreview, photoPreviewStorageKey, formatAmount};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.NutritionTrackingUI = api;
})(globalThis);
