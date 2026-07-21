import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiGetRaw, apiPostFormRaw } from './client';

describe('api client raw envelope helpers', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('keeps mixed legacy envelope fields for control index style responses', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      headers: {
        get: () => 'application/json',
      },
      json: async () => ({
        code: 1000,
        msg: 'success',
        data: [[{ code: 'ctrl-1' }]],
        pageData: { page: 2, page_size: 20, count: 1 },
        stats: { total: 1, running: 1, stopped: 0, error: 0 },
      }),
    });

    const result = await apiGetRaw('/control/openIndex', { p: 2, ps: 20 });

    expect(result.data[0][0].code).toBe('ctrl-1');
    expect(result.pageData.page).toBe(2);
    expect(result.stats.running).toBe(1);
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({
          'X-Beacon-App-Shell': '1',
        }),
      }),
    );
  });

  it('returns the raw upload envelope for non-1000 form responses', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      headers: {
        get: () => 'application/json',
      },
      json: async () => ({
        code: 0,
        msg: '导入失败',
        data: {
          top_msg: 'JSON 文件解析失败',
          license_error: {
            code: 'malformed_json',
            message: 'bad json',
          },
        },
      }),
    });

    const formData = new FormData();
    formData.append('file', new Blob(['bad'], { type: 'application/json' }), 'license.json');

    const result = await apiPostFormRaw('/api/app-shell/license/upload', formData);

    expect(result.code).toBe(0);
    expect(result.msg).toBe('导入失败');
    expect(result.data.license_error.code).toBe('malformed_json');
  });
});
