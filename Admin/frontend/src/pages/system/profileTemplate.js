function parseInnerTemplate(template) {
  if (template?.tagName === 'TEMPLATE') {
    const parser = new DOMParser();
    return parser.parseFromString(`<body>${template.innerHTML || ''}</body>`, 'text/html');
  }

  return null;
}

function getInputValue(doc, selector, fallback = '') {
  const node = doc?.querySelector(selector);
  if (node === null || node === undefined) return fallback;
  return String(node.value ?? fallback);
}

function getTrimmedText(node) {
  return (node?.textContent || '').trim();
}

function getBlockValue(block) {
  if (block === null || block === undefined) return '';
  const clone = block.cloneNode(true);
  clone.querySelector('.label-text')?.remove();
  return getTrimmedText(clone);
}

function parseRecoveryUnusedCount(doc) {
  const value = getTrimmedText(doc?.querySelector('.totp-section p strong'));
  const count = Number.parseInt(value, 10);
  return Number.isNaN(count) ? 0 : count;
}

function parseSecretBlocks(doc) {
  let totpSecret = '';
  let totpOtpauthUri = '';

  Array.from(doc?.querySelectorAll('.totp-secret-block') || []).forEach((block) => {
    const label = getTrimmedText(block.querySelector('.label-text'));
    const value = getBlockValue(block);

    if (!value) return;

    if (label.includes('TOTP 密钥')) {
      totpSecret = value;
      return;
    }

    if (label.includes('otpauth:// URI')) {
      totpOtpauthUri = value;
    }
  });

  return { totpSecret, totpOtpauthUri };
}

function readProfileState(doc) {
  const { totpSecret, totpOtpauthUri } = parseSecretBlocks(doc);
  const statusText = getTrimmedText(doc?.querySelector('.totp-status'));

  return {
    username: getInputValue(doc, '#username'),
    email: getInputValue(doc, '#email'),
    totpEnabled: statusText.includes('已启用'),
    totpSecret,
    totpOtpauthUri,
    recoveryUnusedCount: parseRecoveryUnusedCount(doc),
    recoveryCodes: Array.from(doc?.querySelectorAll('.recovery-codes code') || []).map(node => getTrimmedText(node)).filter(Boolean),
    messageText: getTrimmedText(doc?.querySelector('#profileMsg')),
  };
}

export function readProfileTemplate() {
  const template = document.getElementById('beacon-legacy-content');
  const innerDoc = parseInnerTemplate(template);
  if (!innerDoc) return null;
  return readProfileState(innerDoc);
}

export function parseProfileTemplateFromHtml(html) {
  if (!html) return null;

  const parser = new DOMParser();
  const fullDoc = parser.parseFromString(html, 'text/html');
  const template = fullDoc.getElementById('beacon-legacy-content');
  const innerDoc = parseInnerTemplate(template);
  if (!innerDoc) return null;
  return readProfileState(innerDoc);
}
