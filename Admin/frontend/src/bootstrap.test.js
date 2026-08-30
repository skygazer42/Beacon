import { afterEach, describe, expect, it } from 'vitest';

import { getSiteBranding, normalizeBrowserUrl, resetBootstrapCache } from './bootstrap';


function mountBootstrap(values) {
  const node = document.createElement('script');
  node.id = 'beacon-bootstrap';
  node.type = 'application/json';
  node.textContent = JSON.stringify(values);
  document.body.appendChild(node);
  resetBootstrapCache();
}


describe('bootstrap URL policy', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    resetBootstrapCache();
  });

  it('rejects executable and protocol-relative branding URLs', () => {
    mountBootstrap({
      siteLogo: 'javascript:alert(1)',
      docsUrl: '//evil.example/docs',
      downloadUrl: 'data:text/html,attack',
    });

    expect(getSiteBranding()).toMatchObject({
      logo: '/static/images/logo.png',
      docsUrl: '',
      downloadUrl: '',
    });
  });

  it('allows local assets and http links while stripping credentials', () => {
    expect(normalizeBrowserUrl('/static/images/custom.png', '', { image: true }))
      .toBe('/static/images/custom.png');
    expect(normalizeBrowserUrl('https://user:pass@example.com/logo.png', '', { image: true }))
      .toBe('');
    expect(normalizeBrowserUrl('https://user:pass@example.com/docs'))
      .toBe('https://example.com/docs');
  });
});
