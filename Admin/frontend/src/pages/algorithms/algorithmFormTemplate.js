function getTemplateElement(id = 'beacon-legacy-content') {
  const node = document.getElementById(id);
  if (node?.tagName === 'TEMPLATE') return node;
  return null;
}

function getTemplateDocument() {
  const template = getTemplateElement();
  if (template === null) return null;

  const parser = new DOMParser();
  return parser.parseFromString(`<body>${template.innerHTML || ''}</body>`, 'text/html');
}

function getInputValue(doc, selector, fallback = '') {
  const node = doc?.querySelector(selector);
  if (node === null || node === undefined) return fallback;
  return node.value ?? fallback;
}

function getTextContent(doc, selector) {
  return (doc?.querySelector(selector)?.textContent || '').trim();
}

function parseSelectOptions(doc, selector) {
  const select = doc?.querySelector(selector);
  if (select === null || select === undefined) return [];

  return Array.from(select.querySelectorAll('option'))
    .map(option => ({
      value: option.value,
      label: (option.textContent || '').trim(),
    }))
    .filter(option => option.value);
}

function parseBehaviorOptions(doc) {
  return Array.from(doc?.querySelectorAll('.behavior-option') || [])
    .map(option => ({
      value: option.dataset.value || '',
      label: (option.textContent || '').trim(),
    }))
    .filter(option => option.value);
}

export function readAlgorithmFormTemplate() {
  const doc = getTemplateDocument();
  if (!doc) return null;

  const algorithmType = Number.parseInt(getInputValue(doc, '#algorithm_type', '0'), 10);
  const behaviorApiVersion = Number.parseInt(getInputValue(doc, '#behavior_api_version', '1'), 10);
  const modelExisting = getTextContent(doc, '#basic_model_config .existing-file span').replace(/^已上传:\s*/, '');
  const dllExisting = getTextContent(doc, '#behavior_section .existing-file span').replace(/^已上传:\s*/, '');

  return {
    handle: getInputValue(doc, 'input[name="handle"]', 'add'),
    popupMode:
      Boolean(doc.querySelector('input[name="popup"]')) ||
      doc.querySelector('.bcn-page')?.dataset.popupMode === '1',
    values: {
      code: getInputValue(doc, '#code'),
      name: getInputValue(doc, '#name'),
      algorithmType: Number.isNaN(algorithmType) ? 0 : algorithmType,
      basicSource: getInputValue(doc, '#basic_source', 'model'),
      algorithmSubtype: getInputValue(doc, '#algorithm_subtype', 'detection'),
      licensePackage: getInputValue(doc, '#license_package', 'core'),
      apiUrl: getInputValue(doc, '#api_url_basic'),
      apiUrlBehavior: getInputValue(doc, '#api_url_behavior'),
      supportDirectApi: Boolean(doc.querySelector('#support_direct_api')?.checked),
      behaviorApiVersion: Number.isNaN(behaviorApiVersion) ? 1 : behaviorApiVersion,
      builtinBehavior: getInputValue(doc, '#builtin_behavior'),
      objectStr: getInputValue(doc, '#object_str'),
      remark: getInputValue(doc, '#remark'),
      maxControlCount: getInputValue(doc, '#max_control_count', '0'),
      modelConcurrency: getInputValue(doc, '#model_concurrency', '1'),
      modelPrecision: getInputValue(doc, '#model_precision', 'FP32'),
      inputWidth: getInputValue(doc, '#input_width', '640'),
      inputHeight: getInputValue(doc, '#input_height', '640'),
      confThresh: getInputValue(doc, '#conf_thresh', '0.25'),
      nmsThresh: getInputValue(doc, '#nms_thresh', '0.45'),
    },
    fields: {
      codeReadonly: Boolean(doc.querySelector('#code')?.hasAttribute('readonly')),
    },
    options: {
      subtypes: parseSelectOptions(doc, '#algorithm_subtype_select'),
      modelPrecisions: parseSelectOptions(doc, '#model_precision'),
      behaviorApiVersions: parseSelectOptions(doc, '#behavior_api_version'),
      builtinBehaviors: parseBehaviorOptions(doc),
    },
    existingFiles: {
      modelPath: modelExisting,
      dllPath: dllExisting,
    },
  };
}
