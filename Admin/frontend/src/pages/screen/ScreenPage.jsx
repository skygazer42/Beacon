import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import PropTypes from 'prop-types';
import {
  Card, Spin, Button, Space, Select, Tag, Badge,
  Row, Col, Typography, Segmented, Drawer, List, Input, theme,
} from 'antd';
import {
  DesktopOutlined, ReloadOutlined,
  AlertOutlined, VideoCameraOutlined, SearchOutlined,
  AppstoreOutlined, BorderOutlined,
} from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import KpiCard, { KpiCardGroup } from '../../components/KpiCard';
import useApi from '../../hooks/useApi';
import { apiGetRaw } from '../../api/client';
import { API } from '../../api/endpoints';

const { Text } = Typography;

const SPLIT_OPTIONS = [
  { value: 1, label: '1 画面' },
  { value: 2, label: '2 画面' },
  { value: 4, label: '4 画面' },
  { value: 9, label: '9 画面' },
  { value: 16, label: '16 画面' },
];

const SCREEN_PLAY_URL_CACHE_KEY = '__BEACON_SCREEN_PLAY_URL_CACHE__';

function normalizeSplit(value) {
  const v = Number(value);
  return [1, 2, 4, 9, 16].includes(v) ? v : 4;
}

function handleActivationKey(event, action) {
  if (event.key !== 'Enter' && event.key !== ' ') {
    return;
  }
  event.preventDefault();
  action();
}

function gridDimension(split) {
  return Math.ceil(Math.sqrt(split));
}

function getScreenPlayUrlCacheStore() {
  if (globalThis.window === undefined) {
    return { data: new Map(), inflight: new Map(), requested: new Set() };
  }

  if (!globalThis[SCREEN_PLAY_URL_CACHE_KEY]) {
    globalThis[SCREEN_PLAY_URL_CACHE_KEY] = { data: new Map(), inflight: new Map(), requested: new Set() };
  }
  return globalThis[SCREEN_PLAY_URL_CACHE_KEY];
}

function buildScreenPlayUrlCacheKey(split, app, name) {
  return `${normalizeSplit(split)}|${String(app || '').trim()}/${String(name || '').trim()}`;
}

function readScreenPlayUrlCache(split, app, name) {
  return getScreenPlayUrlCacheStore().data.get(buildScreenPlayUrlCacheKey(split, app, name)) || null;
}

function writeScreenPlayUrlCache(split, app, name, data) {
  const store = getScreenPlayUrlCacheStore();
  const cacheKey = buildScreenPlayUrlCacheKey(split, app, name);
  if (data?.url) {
    store.data.set(cacheKey, data);
    return;
  }
  store.data.delete(cacheKey);
}

function getScreenPlayUrlInflight(split, app, name) {
  return getScreenPlayUrlCacheStore().inflight.get(buildScreenPlayUrlCacheKey(split, app, name)) || null;
}

function setScreenPlayUrlInflight(split, app, name, promise) {
  const store = getScreenPlayUrlCacheStore();
  const cacheKey = buildScreenPlayUrlCacheKey(split, app, name);
  store.inflight.set(cacheKey, promise);
  Promise.resolve(promise).finally(() => {
    if (store.inflight.get(cacheKey) === promise) {
      store.inflight.delete(cacheKey);
    }
  });
}

function clearScreenPlayUrlCache(split = null) {
  const store = getScreenPlayUrlCacheStore();
  if (split === null || split === undefined) {
    store.data.clear();
    store.inflight.clear();
    store.requested.clear();
    return;
  }

  const prefix = `${normalizeSplit(split)}|`;
  [...store.data.keys()].forEach((key) => {
    if (key.startsWith(prefix)) {
      store.data.delete(key);
    }
  });
  [...store.inflight.keys()].forEach((key) => {
    if (key.startsWith(prefix)) {
      store.inflight.delete(key);
    }
  });
  [...store.requested].forEach((key) => {
    if (key.startsWith(prefix)) {
      store.requested.delete(key);
    }
  });
}

function clearScreenPlayUrlCacheEntry(split, app, name) {
  const store = getScreenPlayUrlCacheStore();
  const cacheKey = buildScreenPlayUrlCacheKey(split, app, name);
  store.data.delete(cacheKey);
  store.inflight.delete(cacheKey);
  store.requested.delete(cacheKey);
}

function storeScreenPlayData(playDataMapRef, setPlayDataMap, key, data) {
  playDataMapRef.current = { ...playDataMapRef.current, [key]: data };
  setPlayDataMap(prev => ({ ...prev, [key]: data }));
}

function reuseCachedScreenPlayData({ split, app, name, attempt, playDataMapRef, setPlayDataMap, key }) {
  const cached = attempt === 0 ? readScreenPlayUrlCache(split, app, name) : null;
  if (!cached?.url) {
    return false;
  }
  storeScreenPlayData(playDataMapRef, setPlayDataMap, key, cached);
  return true;
}

async function reuseInflightScreenPlayData({ split, app, name, attempt, playDataMapRef, setPlayDataMap, key }) {
  const pending = attempt === 0 ? getScreenPlayUrlInflight(split, app, name) : null;
  if (!pending) {
    return false;
  }
  try {
    const reused = await pending;
    if (reused?.url) {
      storeScreenPlayData(playDataMapRef, setPlayDataMap, key, reused);
    }
  } catch {
    // ignore shared request errors
  }
  return true;
}

function shouldStartScreenPlayRequest({ attempt, cacheStore, cacheKey }) {
  if (attempt !== 0) {
    return true;
  }
  if (cacheStore.requested.has(cacheKey)) {
    return false;
  }
  cacheStore.requested.add(cacheKey);
  return true;
}

function clearRetryTimer(retryTimersRef, key) {
  if (!retryTimersRef.current[key]) {
    return;
  }
  globalThis.clearTimeout(retryTimersRef.current[key]);
  delete retryTimersRef.current[key];
}

function rememberInitialPlayUrlRequest({ attempt, split, app, name, requestPromise }) {
  if (attempt !== 0) {
    return;
  }
  setScreenPlayUrlInflight(
    split,
    app,
    name,
    requestPromise.then((res) => (res?.code === 1000 && res?.data?.url ? res.data : null)),
  );
}

function scheduleScreenPlayRetry({ retryTimersRef, key, fetchPlayUrl, app, name, attempt, retryAfterMs }) {
  retryTimersRef.current[key] = globalThis.setTimeout(() => {
    delete retryTimersRef.current[key];
    fetchPlayUrl(app, name, attempt + 1);
  }, retryAfterMs);
}

function handleScreenPlayUrlResult({
  res,
  split,
  app,
  name,
  key,
  attempt,
  playDataMapRef,
  setPlayDataMap,
  retryTimersRef,
  fetchPlayUrl,
}) {
  if (res?.code === 1000 && res?.data?.url) {
    writeScreenPlayUrlCache(split, app, name, res.data);
    storeScreenPlayData(playDataMapRef, setPlayDataMap, key, res.data);
    return true;
  }

  if (res?.code !== 1001 || !res?.data?.url) {
    return false;
  }

  writeScreenPlayUrlCache(split, app, name, null);
  storeScreenPlayData(playDataMapRef, setPlayDataMap, key, res.data);
  const retryAfterMs = Math.max(300, Number.parseInt(res.retry_after_ms || 500, 10) || 500);
  scheduleScreenPlayRetry({ retryTimersRef, key, fetchPlayUrl, app, name, attempt, retryAfterMs });
  return true;
}

function clearRequestedAfterPlayUrlError({ attempt, split, app, name, cacheStore, cacheKey }) {
  if (attempt === 0 && !readScreenPlayUrlCache(split, app, name)) {
    cacheStore.requested.delete(cacheKey);
  }
}

function buildOnlineStreamKeySet(streams) {
  const set = new Set();
  (streams || []).forEach((stream) => {
    const app = (stream?.app || '').trim();
    const name = (stream?.name || '').trim();
    if (app && name) {
      set.add(`${app}/${name}`);
    }
  });
  return set;
}

function buildInitialWindowMap(focusRows, split, onlineStreams) {
  const normalized = normalizeSplit(split);
  const onlineKeySet = buildOnlineStreamKeySet(onlineStreams);
  const picked = [];
  const used = new Set();

  (focusRows || []).forEach((row) => {
    const app = (row?.stream_app || '').trim();
    const name = (row?.stream_name || '').trim();
    const key = app && name ? `${app}/${name}` : '';
    if (!key || !onlineKeySet.has(key) || used.has(key)) {
      return;
    }
    used.add(key);
    picked.push({ app, name });
  });

  (onlineStreams || []).forEach((stream) => {
    if (picked.length >= normalized) {
      return;
    }
    const app = (stream?.app || '').trim();
    const name = (stream?.name || '').trim();
    const key = app && name ? `${app}/${name}` : '';
    if (!key || used.has(key)) {
      return;
    }
    used.add(key);
    picked.push({ app, name });
  });

  return picked.slice(0, normalized);
}

function buildScreenPlayableStreams(onlineStreams) {
  const rows = Array.isArray(onlineStreams) ? onlineStreams : [];
  const coveredRawKeys = new Set();

  rows.forEach((stream) => {
    const sourceType = Number(stream?.source_type || 0);
    if (sourceType !== 2) {
      return;
    }
    const rawApp = String(stream?.control_stream_app || '').trim();
    const rawName = String(stream?.control_stream_name || '').trim();
    if (rawApp && rawName) {
      coveredRawKeys.add(`${rawApp}/${rawName}`);
    }
  });

  return rows.filter((stream) => {
    const app = String(stream?.app || '').trim();
    const name = String(stream?.name || '').trim();
    const key = app && name ? `${app}/${name}` : '';
    if (!key) {
      return false;
    }
    const sourceType = Number(stream?.source_type || 0);
    if (sourceType === 1 && coveredRawKeys.has(key)) {
      return false;
    }
    return true;
  });
}

function StreamSlot({ slot, selected, onClick, playData, onRetry }) {
  const { token } = theme.useToken();
  const hasStream = Boolean(slot.streamKey);
  const hasAlarm = slot.alarmCount > 0;
  const embedUrl = playData?.embed_url || playData?.webrtc_url;
  let streamContent = (
    <div style={{ textAlign: 'center' }}>
      <VideoCameraOutlined style={{ fontSize: 24, color: token.colorTextDisabled }} />
      <div style={{ fontSize: 11, color: token.colorTextDisabled, marginTop: 4 }}>
        空闲窗口
      </div>
    </div>
  );
  if (hasStream) {
    streamContent = <Spin size="small" />;
  }
  if (hasStream && playData?.url) {
    streamContent = (
      <video
        src={playData.url}
        autoPlay
        muted
        playsInline
        style={{ width: '100%', height: '100%', objectFit: 'contain' }}
        onError={onRetry}
      />
    );
  }
  if (hasStream && embedUrl) {
    streamContent = (
      <iframe
        title={slot.streamLabel}
        src={embedUrl}
        allow="autoplay; fullscreen; camera; microphone"
        allowFullScreen
        style={{ width: '100%', height: '100%', border: 0, pointerEvents: 'none' }}
      />
    );
  }

  return (
    <button
      type="button"
      aria-label={`选择播放窗口 ${slot.title}`}
      aria-pressed={selected}
      onClick={() => onClick(slot.index)}
      onKeyDown={(event) => handleActivationKey(event, () => onClick(slot.index))}
      style={{
        appearance: 'none',
        display: 'block',
        position: 'relative',
        width: '100%',
        paddingBottom: '56.25%',
        background: hasStream ? '#000' : token.colorBgLayout,
        border: selected
          ? `2px solid ${token.colorPrimary}`
          : `1px solid ${token.colorBorderSecondary}`,
        borderRadius: 4,
        color: 'inherit',
        cursor: 'pointer',
        font: 'inherit',
        overflow: 'hidden',
        textAlign: 'inherit',
        transition: 'border-color 0.2s',
      }}
    >
      <div style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        {streamContent}
      </div>

      {/* Overlay: window number + stream label */}
      <div style={{
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '2px 6px',
        background: 'rgba(0,0,0,0.45)',
        color: '#fff',
        fontSize: 11,
        zIndex: 2,
      }}>
        <span>{slot.title}</span>
        {hasStream && (
          <span style={{ maxWidth: '60%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {slot.streamLabel}
          </span>
        )}
      </div>

      {hasAlarm && (
        <div style={{
          position: 'absolute',
          bottom: 4,
          right: 6,
          zIndex: 2,
        }}>
          <Badge count={slot.alarmCount} size="small" />
        </div>
      )}
    </button>
  );
}

const streamSlotShape = PropTypes.shape({
  index: PropTypes.number.isRequired,
  title: PropTypes.string.isRequired,
  streamKey: PropTypes.string,
  streamLabel: PropTypes.string,
  alarmCount: PropTypes.number,
});

const streamPlayDataShape = PropTypes.shape({
  embed_url: PropTypes.string,
  webrtc_url: PropTypes.string,
  url: PropTypes.string,
});

const onlineStreamShape = PropTypes.shape({
  app: PropTypes.string,
  name: PropTypes.string,
  display_name: PropTypes.string,
  source_nickname: PropTypes.string,
  source_label: PropTypes.string,
  control_code: PropTypes.string,
});

const recentEventShape = PropTypes.shape({
  id: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  desc: PropTypes.string,
  detail_url: PropTypes.string,
});

const focusRowShape = PropTypes.shape({
  stream_code: PropTypes.string,
  stream_app: PropTypes.string,
  stream_name: PropTypes.string,
  label: PropTypes.string,
  group: PropTypes.string,
  alarm_count: PropTypes.number,
  stream_detail_url: PropTypes.string,
  latest_alarm_url: PropTypes.string,
  recent_events: PropTypes.arrayOf(recentEventShape),
});

const groupOptionShape = PropTypes.shape({
  value: PropTypes.string.isRequired,
  label: PropTypes.node.isRequired,
});

StreamSlot.propTypes = {
  slot: streamSlotShape.isRequired,
  selected: PropTypes.bool.isRequired,
  onClick: PropTypes.func.isRequired,
  playData: streamPlayDataShape,
  onRetry: PropTypes.func,
};

function StreamPicker({ open, onClose, streams, onSelect, groupOptions }) {
  const [group, setGroup] = useState('all');
  const [keyword, setKeyword] = useState('');

  const filtered = (streams || []).filter(s => {
    if (group !== 'all' && (s.app || '') !== group) return false;
    if (keyword) {
      const hay = [s.display_name, s.source_nickname, s.app, s.name, s.control_code].join(' ').toLowerCase();
      if (!hay.includes(keyword.toLowerCase())) return false;
    }
    return true;
  }).sort((a, b) => (a.app || '').localeCompare(b.app || '', 'zh-Hans-CN'));

  return (
    <Drawer
      title="选择视频流投放到窗口"
      open={open}
      onClose={onClose}
      width={420}
      styles={{ body: { padding: '12px 16px' } }}
    >
      <Space direction="vertical" size={8} style={{ width: '100%', marginBottom: 12 }}>
        <Select
          value={group}
          onChange={setGroup}
          options={groupOptions}
          style={{ width: '100%' }}
          size="small"
        />
        <Input
          prefix={<SearchOutlined style={{ color: '#d1d5db' }} />}
          placeholder="搜索流名称/编号"
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          allowClear
          size="small"
        />
      </Space>
      <List
        size="small"
        dataSource={filtered}
        locale={{ emptyText: '无匹配在线流' }}
        renderItem={item => (
          <List.Item
            style={{ cursor: 'pointer', padding: '6px 0' }}
            onClick={() => { onSelect(item); onClose(); }}
          >
            <List.Item.Meta
              title={<Text style={{ fontSize: 13 }}>{item.display_name || item.name || '-'}</Text>}
              description={
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {item.app}/{item.name}
                  {item.source_label ? ` (${item.source_label})` : ''}
                </Text>
              }
            />
          </List.Item>
        )}
      />
    </Drawer>
  );
}

StreamPicker.propTypes = {
  open: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  streams: PropTypes.arrayOf(onlineStreamShape).isRequired,
  onSelect: PropTypes.func.isRequired,
  groupOptions: PropTypes.arrayOf(groupOptionShape).isRequired,
};

function RecentEventsPanel({ focusRows }) {
  const events = (focusRows || [])
    .flatMap(row =>
      (row.recent_events || []).map(evt => ({
        key: `${row.stream_code}-${evt.id}`,
        id: evt.id,
        desc: evt.desc || '未命名事件',
        stream: row.label || row.stream_code,
        href: evt.detail_url,
        streamApp: row.stream_app,
        streamName: row.stream_name,
      }))
    )
    .sort((a, b) => (b.id || 0) - (a.id || 0))
    .slice(0, 10);

  if (events.length === 0) return null;

  return (
    <Card
      size="small"
      title={<><AlertOutlined style={{ marginRight: 6 }} />最近告警</>}
      styles={{ body: { padding: '4px 12px', maxHeight: 300, overflow: 'auto' } }}
    >
      {events.map(evt => (
        <div key={evt.key} style={{
          padding: '5px 0',
          borderBottom: '1px solid var(--beacon-border-muted)',
          fontSize: 12,
        }}>
          <div>
            <Text strong style={{ fontSize: 12 }}>{evt.stream}</Text>
            {evt.href && (
              <a href={evt.href} style={{ marginLeft: 8, fontSize: 11 }}>查看</a>
            )}
          </div>
          <Text type="secondary" style={{ fontSize: 11 }}>{evt.desc}</Text>
        </div>
      ))}
    </Card>
  );
}

RecentEventsPanel.propTypes = {
  focusRows: PropTypes.arrayOf(focusRowShape).isRequired,
};

function FocusOverviewPanel({ focusRows }) {
  if (!focusRows?.length) return null;

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>在线视频流概览</div>
      <Row gutter={[12, 12]}>
        {focusRows.map((row) => (
          <Col key={row.stream_code || `${row.stream_app}-${row.stream_name}`} xs={24} md={12} xl={8}>
            <Card
              size="small"
              styles={{ body: { padding: 14 } }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
                <Text strong>{row.label || row.stream_code || '-'}</Text>
                <Tag color="error" style={{ marginInlineEnd: 0 }}>
                  {row.alarm_count || 0} 报警
                </Tag>
              </div>

              <Text type="secondary" style={{ display: 'block', fontSize: 12, marginBottom: 10 }}>
                {(row.group || row.stream_app || '-')}{' '}
                · {row.stream_code || `${row.stream_app || ''}/${row.stream_name || ''}`}
              </Text>

              <Space size={8} wrap style={{ marginBottom: row.recent_events?.length ? 10 : 0 }}>
                {row.stream_detail_url ? (
                  <Button size="small" type="primary" href={row.stream_detail_url}>
                    打开视频流
                  </Button>
                ) : null}
                {row.latest_alarm_url ? (
                  <Button size="small" href={row.latest_alarm_url}>
                    最近报警
                  </Button>
                ) : null}
              </Space>

              {row.recent_events?.length ? (
                <Space size={[6, 6]} wrap>
                  {row.recent_events.map((event) => (
                    <Tag key={`${row.stream_code}-${event.id}`} color="processing" style={{ marginInlineEnd: 0 }}>
                      {event.desc || '未命名事件'}
                    </Tag>
                  ))}
                </Space>
              ) : null}
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
}

FocusOverviewPanel.propTypes = {
  focusRows: PropTypes.arrayOf(focusRowShape).isRequired,
};

export default function ScreenPage() {
  const { data: screenData, run: refreshScreen } = useApi(API.screen);
  const { data: onlineData, run: refreshOnline } = useApi(API.streamOnline);

  const [split, setSplit] = useState(4);
  const [selectedWindow, setSelectedWindow] = useState(0);
  const [windowMap, setWindowMap] = useState([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [playDataMap, setPlayDataMap] = useState({});

  const focusRows = screenData?.rows || [];
  const onlineStreams = onlineData?.rows || [];
  const playableStreams = useMemo(() => buildScreenPlayableStreams(onlineStreams), [onlineStreams]);
  const onlineSummary = onlineData?.summary || {};

  const inflightRequestRef = useRef(new Set());
  const retryTimersRef = useRef({});
  const playDataMapRef = useRef({});
  const previousSplitRef = useRef(split);

  const groupOptions = buildGroupOptions(playableStreams);

  useEffect(() => {
    if (windowMap.length === 0) {
      const initial = buildInitialWindowMap(focusRows, split, playableStreams);
      setWindowMap(initial);
    }
  }, [focusRows, playableStreams, split, windowMap.length]);

  useEffect(() => {
    if (previousSplitRef.current !== split) {
      clearScreenPlayUrlCache();
      previousSplitRef.current = split;
    }
    playDataMapRef.current = {};
    setPlayDataMap({});
  }, [split]);

  const fetchPlayUrl = useCallback(async (app, name, attempt = 0) => {
    const key = `${app}/${name}`;
    const cacheKey = buildScreenPlayUrlCacheKey(split, app, name);
    const cacheStore = getScreenPlayUrlCacheStore();
    const current = playDataMapRef.current[key];
    if (current?.url && attempt === 0) return;
    if (inflightRequestRef.current.has(key)) return;

    if (reuseCachedScreenPlayData({ split, app, name, attempt, playDataMapRef, setPlayDataMap, key })) {
      return;
    }

    if (await reuseInflightScreenPlayData({ split, app, name, attempt, playDataMapRef, setPlayDataMap, key })) {
      return;
    }
    if (!shouldStartScreenPlayRequest({ attempt, cacheStore, cacheKey })) {
      return;
    }
    inflightRequestRef.current.add(key);
    clearRetryTimer(retryTimersRef, key);

    try {
      const requestPromise = apiGetRaw(API.streamGetPlayUrl, {
        app,
        name,
        layout: split,
        prefer: 'compat',
        quality: 'auto',
      });
      rememberInitialPlayUrlRequest({ attempt, split, app, name, requestPromise });
      const res = await requestPromise;
      handleScreenPlayUrlResult({ res, split, app, name, key, attempt, playDataMapRef, setPlayDataMap, retryTimersRef, fetchPlayUrl });
    } catch {
      clearRequestedAfterPlayUrlError({ attempt, split, app, name, cacheStore, cacheKey });
    } finally {
      inflightRequestRef.current.delete(key);
    }
  }, [split]);

  useEffect(() => {
    windowMap.forEach(slot => {
      if (slot?.app && slot?.name) {
        fetchPlayUrl(slot.app, slot.name);
      }
    });
  }, [windowMap, fetchPlayUrl]);

  useEffect(() => () => {
    Object.values(retryTimersRef.current).forEach((timerId) => globalThis.clearTimeout(timerId));
    retryTimersRef.current = {};
  }, []);

  const handleSelectStream = useCallback((stream) => {
    setWindowMap(prev => {
      const next = [...prev];
      while (next.length <= selectedWindow) next.push(null);
      next[selectedWindow] = { app: stream.app || '', name: stream.name || '' };
      return next;
    });
    const key = `${stream.app}/${stream.name}`;
    if (!playDataMapRef.current[key]?.url) {
      fetchPlayUrl(stream.app, stream.name);
    }
  }, [selectedWindow, fetchPlayUrl]);

  const handleClearWindow = useCallback(() => {
    setWindowMap(prev => {
      const next = [...prev];
      if (next[selectedWindow]) next[selectedWindow] = null;
      return next;
    });
  }, [selectedWindow]);

  const handleRefreshAll = useCallback(() => {
    clearScreenPlayUrlCache();
    playDataMapRef.current = {};
    setPlayDataMap({});
    refreshScreen();
    refreshOnline();
  }, [refreshScreen, refreshOnline]);

  const windows = buildWindowAssignments(split, windowMap, focusRows, playableStreams);
  const assignedCount = windows.filter(w => w.streamKey).length;
  const alarmTotal = focusRows.reduce((sum, r) => sum + (r.alarm_count || 0), 0);

  return (
    <div>
      <PageHeader
        title="数字大屏"
        icon={<DesktopOutlined />}
        description="大屏展示管理"
        extra={
          <Space>
            <Segmented
              size="small"
              options={SPLIT_OPTIONS}
              value={split}
              onChange={v => { setSplit(v); setSelectedWindow(0); }}
            />
            <Button icon={<ReloadOutlined />} size="small" onClick={handleRefreshAll}>刷新</Button>
          </Space>
        }
      />

      <FocusOverviewPanel focusRows={focusRows} />

      <KpiCardGroup>
        <KpiCard title="在线流" value={playableStreams.length || onlineSummary.total_count || 0} icon={<VideoCameraOutlined />} />
        <KpiCard title="热点流" value={focusRows.length} icon={<AlertOutlined />} color="#fa541c" />
        <KpiCard title="当前分屏" value={`${split} 宫格`} icon={<AppstoreOutlined />} />
        <KpiCard title="已投放" value={`${assignedCount} / ${split}`} icon={<BorderOutlined />} color="#2563eb" />
        {alarmTotal > 0 && (
          <KpiCard title="活跃告警" value={alarmTotal} icon={<AlertOutlined />} color="#dc2626" />
        )}
      </KpiCardGroup>

      <Row gutter={16}>
        <Col xs={24} lg={18}>
          <Card
            size="small"
            title={`监控画面 (${split} 宫格)`}
            styles={{ body: { padding: 8, background: '#111' } }}
            extra={
              <Space size={4}>
                <Button
                  type="primary"
                  size="small"
                  onClick={() => setPickerOpen(true)}
                >
                  投放到 {String(selectedWindow + 1).padStart(2, '0')} 号窗
                </Button>
                <Button size="small" onClick={handleClearWindow}>
                  清空窗口
                </Button>
              </Space>
            }
          >
            <div style={{
              display: 'grid',
              gridTemplateColumns: `repeat(${gridDimension(split)}, minmax(0, 1fr))`,
              gap: 4,
            }}>
              {windows.map(slot => (
                <StreamSlot
                  key={slot.index}
                  slot={slot}
                  selected={slot.index === selectedWindow}
                  onClick={setSelectedWindow}
                  playData={slot.streamKey ? playDataMap[slot.streamKey] : null}
                  onRetry={() => {
                    if (slot.streamKey) {
                      const parts = slot.streamKey.split('/');
                      if (parts.length === 2) {
                        clearScreenPlayUrlCacheEntry(split, parts[0], parts[1]);
                      }
                      playDataMapRef.current = Object.fromEntries(
                        Object.entries(playDataMapRef.current).filter(([key]) => key !== slot.streamKey),
                      );
                      setPlayDataMap(prev => {
                        const next = { ...prev };
                        delete next[slot.streamKey];
                        return next;
                      });
                      if (parts.length === 2) fetchPlayUrl(parts[0], parts[1]);
                    }
                  }}
                />
              ))}
            </div>
          </Card>
        </Col>

        <Col xs={24} lg={6}>
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Card size="small" title="窗口信息" styles={{ body: { padding: '8px 12px' } }}>
              {(() => {
                const w = windows[selectedWindow];
                if (!w) return <Text type="secondary">未选中窗口</Text>;
                return (
                  <div style={{ fontSize: 13 }}>
                    <div><Text strong>{w.title}</Text></div>
                    <div style={{ marginTop: 4 }}>
                      <Text type="secondary">流：</Text>
                      {w.streamKey ? (
                        <Text>{w.streamLabel}</Text>
                      ) : (
                        <Text type="secondary">等待投放</Text>
                      )}
                    </div>
                    {w.streamKey && (
                      <div style={{ marginTop: 4 }}>
                        <Text type="secondary">标识：</Text>
                        <Text copyable style={{ fontSize: 11 }}>{w.streamKey}</Text>
                      </div>
                    )}
                    {w.alarmCount > 0 && (
                      <div style={{ marginTop: 4 }}>
                        <Badge status="error" text={`${w.alarmCount} 条告警`} />
                      </div>
                    )}
                  </div>
                );
              })()}
            </Card>

            <RecentEventsPanel focusRows={focusRows} />

            <Card
              size="small"
              title="窗口分配"
              styles={{ body: { padding: '4px 8px', maxHeight: 280, overflow: 'auto' } }}
            >
              {windows.map(w => (
                <button
                  key={w.index}
                  type="button"
                  aria-label={`选择窗口分配 ${w.title}`}
                  aria-pressed={w.index === selectedWindow}
                  onClick={() => setSelectedWindow(w.index)}
                  onKeyDown={(event) => handleActivationKey(event, () => setSelectedWindow(w.index))}
                  style={{
                    appearance: 'none',
                    width: '100%',
                    padding: '4px 6px',
                    color: 'inherit',
                    cursor: 'pointer',
                    borderRadius: 4,
                    font: 'inherit',
                    fontSize: 12,
                    background: w.index === selectedWindow ? 'var(--beacon-tone-blue-head)' : 'transparent',
                    border: 0,
                    borderBottom: '1px solid var(--beacon-border-muted)',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    textAlign: 'left',
                  }}
                >
                  <span>
                    <Text strong style={{ fontSize: 12 }}>{w.title}</Text>
                    <Text type="secondary" style={{ fontSize: 11, marginLeft: 6 }}>
                      {w.streamLabel}
                    </Text>
                  </span>
                  {w.streamKey && w.online && (
                    <Tag color="success" style={{ fontSize: 10, margin: 0, lineHeight: '16px' }}>在线</Tag>
                  )}
                </button>
              ))}
            </Card>
          </Space>
        </Col>
      </Row>

        <StreamPicker
          open={pickerOpen}
          onClose={() => setPickerOpen(false)}
          streams={playableStreams}
          onSelect={handleSelectStream}
          groupOptions={groupOptions}
        />
    </div>
  );
}

function buildGroupOptions(streams) {
  const counts = new Map();
  (streams || []).forEach(s => {
    const app = (s.app || '').trim();
    if (app) counts.set(app, (counts.get(app) || 0) + 1);
  });
  const options = [{ value: 'all', label: `全部分组 (${streams?.length || 0})` }];
  [...counts.keys()].sort((a, b) => a.localeCompare(b, 'zh-Hans-CN')).forEach(app => {
    options.push({ value: app, label: `${app} (${counts.get(app)})` });
  });
  return options;
}

function buildWindowAssignments(split, windowMap, focusRows, onlineStreams) {
  const normalized = normalizeSplit(split);
  const mapping = (windowMap || []).slice(0, 16);
  const streamNameMap = new Map();
  (onlineStreams || []).forEach(s => {
    const key = `${(s.app || '').trim()}/${(s.name || '').trim()}`;
    if (key !== '/') {
      streamNameMap.set(key, s.display_name || s.source_nickname || s.name || '未命名');
    }
  });
  const alarmMap = new Map();
  (focusRows || []).forEach(row => {
    const key = `${(row.stream_app || '').trim()}/${(row.stream_name || '').trim()}`;
    if (key !== '/') {
      alarmMap.set(key, (alarmMap.get(key) || 0) + (row.alarm_count || 0));
    }
  });

  return Array.from({ length: normalized }, (_, i) => {
    const assigned = mapping[i] || {};
    const app = (assigned.app || '').trim();
    const name = (assigned.name || '').trim();
    const streamKey = app && name ? `${app}/${name}` : '';
    const streamLabel = streamKey
      ? (streamNameMap.get(streamKey) || focusRows.find(r => r.stream_app === app && r.stream_name === name)?.label || '等待投放')
      : '等待投放';
    return {
      index: i,
      title: `${String(i + 1).padStart(2, '0')} 号窗`,
      streamLabel,
      streamKey,
      online: Boolean(streamKey && streamNameMap.has(streamKey)),
      alarmCount: streamKey ? (alarmMap.get(streamKey) || 0) : 0,
    };
  });
}
