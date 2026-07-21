import React, { useCallback, useEffect, useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import {
  AudioOutlined,
  LinkOutlined,
  PlayCircleOutlined,
  RadarChartOutlined,
  ReloadOutlined,
  SoundOutlined,
} from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import SkeletonPage from '../../components/Skeleton';
import KpiCard, { KpiCardGroup } from '../../components/KpiCard';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { apiGet, apiGetRaw, apiPost } from '../../api/client';
import { getBootstrapQuery } from '../../bootstrap';

const { Paragraph, Text } = Typography;

const LAYOUT_OPTIONS = [
  { value: 1, label: '1 宫格' },
  { value: 2, label: '2 宫格' },
  { value: 4, label: '4 宫格' },
  { value: 9, label: '9 宫格' },
  { value: 16, label: '16 宫格' },
];

function renderCopyableUrl(url) {
  if (!url) {
    return <Text type="secondary">-</Text>;
  }

  return (
    <Paragraph
      copyable={{ text: url }}
      ellipsis={{ rows: 2, tooltip: url }}
      style={{ marginBottom: 0, wordBreak: 'break-all' }}
    >
      {url}
    </Paragraph>
  );
}

function talkbackStatusTag(statusPayload) {
  if (!statusPayload) return null;
  const state = String(statusPayload?.state || '').trim().toLowerCase();
  const active = Boolean(statusPayload?.active);
  if (active || state === 'running') {
    return <Tag color="success">运行中</Tag>;
  }
  if (state === 'stopped' || state === 'idle') {
    return <Tag>已停止</Tag>;
  }
  return <Tag color="processing">{state || '未知'}</Tag>;
}

function buildStreamPlayerTitle(stream, app, name, code) {
  const key = stream.stream_code
    || [stream.app, stream.name].filter(Boolean).join('/')
    || [app, name].filter(Boolean).join('/')
    || code;
  return `播放器 - ${key}`;
}

function protocolActionCell(row) {
  if (!row.action_href) {
    return <Text type="secondary">-</Text>;
  }
  return (
    <Button
      type="link"
      size="small"
      href={row.action_href}
      target="_blank"
      rel="noreferrer"
    >
      {row.action_label || '打开'}
    </Button>
  );
}

function showPlaybackResultMessage(messageApi, res) {
  if (res?.code === 1000) {
    messageApi.success(res?.msg || '已生成播放地址');
    return;
  }
  if (res?.code === 1001) {
    messageApi.warning(res?.msg || '转码尚未就绪');
    return;
  }
  messageApi.warning(res?.msg || '后端返回了异常状态');
}

function buildPlaybackStatusText(playbackResult) {
  if (!playbackResult) {
    return '';
  }
  return [playbackResult.msg, playbackResult.retry_after_ms ? `${playbackResult.retry_after_ms} ms` : '']
    .filter(Boolean)
    .join(' | ');
}

function streamSelfcheckUrl({ webrtc, stream, app, name }) {
  if (!webrtc.selfcheck_endpoint) {
    return '';
  }
  const streamApp = encodeURIComponent(stream.app || app);
  const streamName = encodeURIComponent(stream.name || name);
  return `${webrtc.selfcheck_endpoint}?app=${streamApp}&name=${streamName}`;
}

function StreamPlayerHeaderExtra({ exists, webrtc }) {
  if (!exists) {
    return <Button href="/stream/index">返回列表</Button>;
  }

  return (
    <Space wrap>
      {webrtc.open_url ? (
        <Button href={webrtc.open_url} target="_blank" rel="noreferrer">
          打开 WebRTC
        </Button>
      ) : null}
      <Button href="/stream/index">返回列表</Button>
    </Space>
  );
}

function PlaybackAddressCard({
  stream,
  playback,
  playParams,
  playbackUrl,
  playbackStatusText,
  playbackLoading,
  onParamsChange,
  onGeneratePlayUrl,
}) {
  return (
    <Card
      size="small"
      title="播放地址"
      extra={<Text type="secondary" style={{ fontSize: 12 }}>以后端 `getPlayUrl` 返回为准</Text>}
      style={{ marginBottom: 16 }}
    >
      <Descriptions
        bordered
        size="small"
        column={1}
        items={[
          { key: 'stream_code', label: '视频流编号', children: stream.stream_code || '-' },
          { key: 'app_name', label: '媒体流', children: [stream.app, stream.name].filter(Boolean).join('/') || '-' },
          { key: 'recommended', label: '推荐地址', children: renderCopyableUrl(playback.recommended_url) },
        ]}
      />

      <Space wrap style={{ marginTop: 16 }}>
        <Select
          value={playParams.prefer}
          style={{ minWidth: 220 }}
          popupMatchSelectWidth={false}
          options={(playback.prefer_options || []).map((item) => ({
            value: item.value,
            label: item.label,
          }))}
          onChange={(value) => onParamsChange((prev) => ({ ...prev, prefer: value }))}
        />
        <Select
          value={playParams.quality}
          style={{ width: 120 }}
          options={(playback.quality_options || []).map((item) => ({
            value: item.value,
            label: item.label,
          }))}
          onChange={(value) => onParamsChange((prev) => ({ ...prev, quality: value }))}
        />
        <Select
          value={playParams.layout}
          style={{ width: 110 }}
          options={LAYOUT_OPTIONS}
          onChange={(value) => onParamsChange((prev) => ({ ...prev, layout: value }))}
        />
        <Button
          type="primary"
          icon={<ReloadOutlined />}
          onClick={onGeneratePlayUrl}
          loading={playbackLoading}
        >
          生成播放地址
        </Button>
      </Space>

      <Descriptions
        bordered
        size="small"
        column={1}
        style={{ marginTop: 16 }}
        items={[
          {
            key: 'resolved_url',
            label: '当前地址',
            children: renderCopyableUrl(playbackUrl),
          },
          {
            key: 'resolved_status',
            label: '最近结果',
            children: playbackStatusText || <Text type="secondary">尚未调用</Text>,
          },
        ]}
      />
    </Card>
  );
}

function ProtocolAddressCard({ columns, rows }) {
  return (
    <Card size="small" title="协议地址" style={{ marginBottom: 16 }}>
      <Table
        size="small"
        pagination={false}
        columns={columns}
        dataSource={rows || []}
        rowKey={(row) => row.key}
      />
    </Card>
  );
}

function AudioTracksCard({ columns, tracks }) {
  const rows = tracks || [];
  return (
    <Card size="small" title="音轨信息">
      {rows.length ? (
        <Table
          size="small"
          pagination={false}
          columns={columns}
          dataSource={rows}
          rowKey={(row) => [
            row.codec_id_name || 'audio',
            row.sample_rate || 0,
            row.channels || 0,
            row.sample_bit || 0,
          ].join('-')}
        />
      ) : (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="当前流没有音轨信息"
        />
      )}
    </Card>
  );
}

function WebrtcInfoCard({ webrtc, stream, app, name }) {
  return (
    <Card
      size="small"
      title="WebRTC / 自检入口"
      extra={<RadarChartOutlined />}
      style={{ marginBottom: 16 }}
    >
      <Descriptions
        bordered
        size="small"
        column={1}
        items={[
          { key: 'api_url', label: 'WebRTC API', children: renderCopyableUrl(webrtc.api_url) },
          { key: 'open_url', label: '播放页', children: renderCopyableUrl(webrtc.open_url) },
          { key: 'selfcheck', label: '自检接口', children: renderCopyableUrl(streamSelfcheckUrl({ webrtc, stream, app, name })) },
          { key: 'stun', label: 'STUN', children: <WebrtcStunUrls urls={webrtc.stun_urls || []} /> },
          { key: 'turn', label: 'TURN', children: webrtc.turn_url || '-' },
          { key: 'turn_username', label: 'TURN 用户', children: webrtc.turn_username || '-' },
          { key: 'turn_password', label: 'TURN 密码', children: webrtc.turn_password_masked || '-' },
        ]}
      />
    </Card>
  );
}

function WebrtcStunUrls({ urls }) {
  if (!urls.length) {
    return '-';
  }
  return (
    <Space direction="vertical" size={4} style={{ width: '100%' }}>
      {urls.map((item) => (
        <Text key={item}>{item}</Text>
      ))}
    </Space>
  );
}

function TalkbackCard({
  talkback,
  available,
  status,
  submitting,
  onRefresh,
  onStart,
  onStop,
}) {
  return (
    <Card
      size="small"
      title="Talkback"
      extra={talkbackStatusTag(status)}
    >
      {available ? (
        <TalkbackDetails
          talkback={talkback}
          status={status}
          submitting={submitting}
          onRefresh={onRefresh}
          onStart={onStart}
          onStop={onStop}
        />
      ) : (
        <Alert
          type="warning"
          showIcon
          message={talkback.reason || '当前流未开启 talkback 能力'}
        />
      )}
    </Card>
  );
}

function TalkbackDetails({ talkback, status, submitting, onRefresh, onStart, onStop }) {
  return (
    <>
      <Descriptions
        bordered
        size="small"
        column={1}
        items={[
          { key: 'session', label: 'Session ID', children: talkback.session_id },
          { key: 'stream_code', label: '视频流编号', children: talkback.stream_code },
          { key: 'transport', label: '传输模式', children: talkback.transport_mode || '-' },
          { key: 'sample_rate', label: '采样率', children: talkback.sample_rate ? `${talkback.sample_rate} Hz` : '-' },
          { key: 'codec_hint', label: '编码提示', children: talkback.codec_hint || '-' },
          { key: 'destination_hint', label: '目标地址', children: renderCopyableUrl(talkback.destination_hint) },
          { key: 'push_rtsp', label: 'Push RTSP', children: renderCopyableUrl(talkback.push_rtsp_url) },
          { key: 'push_webrtc_api', label: 'Push WebRTC API', children: renderCopyableUrl(talkback.push_webrtc_api_url) },
          { key: 'push_webrtc_demo', label: 'Push WebRTC Demo', children: renderCopyableUrl(talkback.push_webrtc_demo_url) },
        ]}
      />

      <Space wrap style={{ marginTop: 16 }}>
        <Button onClick={onRefresh} loading={submitting}>
          查询回讲状态
        </Button>
        <Button type="primary" onClick={onStart} loading={submitting}>
          启动回讲
        </Button>
        <Button danger onClick={onStop} loading={submitting}>
          停止回讲
        </Button>
      </Space>

      <Card
        size="small"
        type="inner"
        title="最近状态"
        style={{ marginTop: 16 }}
      >
        <pre
          style={{
            margin: 0,
            fontSize: 11,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
          }}
        >
          {JSON.stringify(status || {}, null, 2)}
        </pre>
      </Card>
    </>
  );
}

function StreamPlayerTips({ webrtc, talkback }) {
  return (
    <Card
      size="small"
      title="说明"
      style={{ marginTop: 16 }}
    >
      <Space direction="vertical" size={8}>
        <Text>
          当前页优先对齐后端接口能力，不内嵌自定义播放器内核。
        </Text>
        <Text type="secondary">
          协议地址、WebRTC 参数和 talkback 元数据都以后端 `app-shell/stream-player` 与直连接口返回为准。
        </Text>
        <Space wrap>
          {webrtc.open_url ? (
            <Button
              type="link"
              icon={<LinkOutlined />}
              href={webrtc.open_url}
              target="_blank"
              rel="noreferrer"
            >
              打开 WebRTC 播放页
            </Button>
          ) : null}
          {talkback.push_webrtc_demo_url ? (
            <Button
              type="link"
              icon={<SoundOutlined />}
              href={talkback.push_webrtc_demo_url}
              target="_blank"
              rel="noreferrer"
            >
              打开 Push Demo
            </Button>
          ) : null}
        </Space>
      </Space>
    </Card>
  );
}

function StreamPlayerKpis({ stream }) {
  return (
    <KpiCardGroup>
      <KpiCard
        title="在线状态"
        value={stream.is_online ? '在线' : '离线'}
        icon={<PlayCircleOutlined />}
        color={stream.is_online ? '#16a34a' : '#f59e0b'}
      />
      <KpiCard title="视频编码" value={stream.video_codec_name || '-'} color="#2563eb" />
      <KpiCard title="分辨率" value={stream.video_resolution || '-'} color="#13c2c2" />
      <KpiCard title="音轨数量" value={(stream.audio_tracks || []).length} icon={<AudioOutlined />} color="#7c3aed" />
    </KpiCardGroup>
  );
}

function StreamPlayerMainColumn({
  stream,
  playback,
  playParams,
  playbackUrl,
  playbackStatusText,
  playbackLoading,
  protocolColumns,
  audioColumns,
  onParamsChange,
  onGeneratePlayUrl,
}) {
  return (
    <Col xs={24} xl={14}>
      <PlaybackAddressCard
        stream={stream}
        playback={playback}
        playParams={playParams}
        playbackUrl={playbackUrl}
        playbackStatusText={playbackStatusText}
        playbackLoading={playbackLoading}
        onParamsChange={onParamsChange}
        onGeneratePlayUrl={onGeneratePlayUrl}
      />
      <ProtocolAddressCard columns={protocolColumns} rows={playback.protocol_rows} />
      <AudioTracksCard columns={audioColumns} tracks={stream.audio_tracks} />
    </Col>
  );
}

function StreamPlayerSideColumn({
  app,
  name,
  stream,
  webrtc,
  talkback,
  talkbackAvailable,
  talkbackStatus,
  talkbackSubmitting,
  onRefreshTalkback,
  onStartTalkback,
  onStopTalkback,
}) {
  return (
    <Col xs={24} xl={10}>
      <WebrtcInfoCard webrtc={webrtc} stream={stream} app={app} name={name} />
      <TalkbackCard
        talkback={talkback}
        available={talkbackAvailable}
        status={talkbackStatus}
        submitting={talkbackSubmitting}
        onRefresh={onRefreshTalkback}
        onStart={onStartTalkback}
        onStop={onStopTalkback}
      />
      <StreamPlayerTips webrtc={webrtc} talkback={talkback} />
    </Col>
  );
}

function StreamPlayerContent({
  app,
  name,
  stream,
  playback,
  webrtc,
  talkback,
  talkbackAvailable,
  talkbackStatus,
  talkbackSubmitting,
  playParams,
  playbackUrl,
  playbackStatusText,
  playbackLoading,
  protocolColumns,
  audioColumns,
  onParamsChange,
  onGeneratePlayUrl,
  onRefreshTalkback,
  onStartTalkback,
  onStopTalkback,
}) {
  return (
    <>
      <StreamPlayerKpis stream={stream} />
      <Row gutter={[16, 16]}>
        <StreamPlayerMainColumn
          stream={stream}
          playback={playback}
          playParams={playParams}
          playbackUrl={playbackUrl}
          playbackStatusText={playbackStatusText}
          playbackLoading={playbackLoading}
          protocolColumns={protocolColumns}
          audioColumns={audioColumns}
          onParamsChange={onParamsChange}
          onGeneratePlayUrl={onGeneratePlayUrl}
        />
        <StreamPlayerSideColumn
          app={app}
          name={name}
          stream={stream}
          webrtc={webrtc}
          talkback={talkback}
          talkbackAvailable={talkbackAvailable}
          talkbackStatus={talkbackStatus}
          talkbackSubmitting={talkbackSubmitting}
          onRefreshTalkback={onRefreshTalkback}
          onStartTalkback={onStartTalkback}
          onStopTalkback={onStopTalkback}
        />
      </Row>
    </>
  );
}

StreamPlayerHeaderExtra.propTypes = {
  exists: PropTypes.bool,
  webrtc: PropTypes.object,
};

PlaybackAddressCard.propTypes = {
  stream: PropTypes.object,
  playback: PropTypes.object,
  playParams: PropTypes.object,
  playbackUrl: PropTypes.string,
  playbackStatusText: PropTypes.node,
  playbackLoading: PropTypes.bool,
  onParamsChange: PropTypes.func,
  onGeneratePlayUrl: PropTypes.func,
};

ProtocolAddressCard.propTypes = {
  columns: PropTypes.array,
  rows: PropTypes.array,
};

AudioTracksCard.propTypes = {
  columns: PropTypes.array,
  tracks: PropTypes.array,
};

WebrtcInfoCard.propTypes = {
  webrtc: PropTypes.object,
  stream: PropTypes.object,
  app: PropTypes.string,
  name: PropTypes.string,
};

WebrtcStunUrls.propTypes = {
  urls: PropTypes.array,
};

TalkbackCard.propTypes = {
  talkback: PropTypes.object,
  available: PropTypes.bool,
  status: PropTypes.object,
  submitting: PropTypes.bool,
  onRefresh: PropTypes.func,
  onStart: PropTypes.func,
  onStop: PropTypes.func,
};

TalkbackDetails.propTypes = {
  talkback: PropTypes.object,
  status: PropTypes.object,
  submitting: PropTypes.bool,
  onRefresh: PropTypes.func,
  onStart: PropTypes.func,
  onStop: PropTypes.func,
};

StreamPlayerTips.propTypes = {
  webrtc: PropTypes.object,
  talkback: PropTypes.object,
};

StreamPlayerKpis.propTypes = {
  stream: PropTypes.object,
};

StreamPlayerMainColumn.propTypes = {
  stream: PropTypes.object,
  playback: PropTypes.object,
  playParams: PropTypes.object,
  playbackUrl: PropTypes.string,
  playbackStatusText: PropTypes.node,
  playbackLoading: PropTypes.bool,
  protocolColumns: PropTypes.array,
  audioColumns: PropTypes.array,
  onParamsChange: PropTypes.func,
  onGeneratePlayUrl: PropTypes.func,
};

StreamPlayerSideColumn.propTypes = {
  app: PropTypes.string,
  name: PropTypes.string,
  stream: PropTypes.object,
  webrtc: PropTypes.object,
  talkback: PropTypes.object,
  talkbackAvailable: PropTypes.bool,
  talkbackStatus: PropTypes.object,
  talkbackSubmitting: PropTypes.bool,
  onRefreshTalkback: PropTypes.func,
  onStartTalkback: PropTypes.func,
  onStopTalkback: PropTypes.func,
};

StreamPlayerContent.propTypes = {
  app: PropTypes.string,
  name: PropTypes.string,
  stream: PropTypes.object,
  playback: PropTypes.object,
  webrtc: PropTypes.object,
  talkback: PropTypes.object,
  talkbackAvailable: PropTypes.bool,
  talkbackStatus: PropTypes.object,
  talkbackSubmitting: PropTypes.bool,
  playParams: PropTypes.object,
  playbackUrl: PropTypes.string,
  playbackStatusText: PropTypes.node,
  playbackLoading: PropTypes.bool,
  protocolColumns: PropTypes.array,
  audioColumns: PropTypes.array,
  onParamsChange: PropTypes.func,
  onGeneratePlayUrl: PropTypes.func,
  onRefreshTalkback: PropTypes.func,
  onStartTalkback: PropTypes.func,
  onStopTalkback: PropTypes.func,
};

export default function StreamPlayerPage() {
  const { message } = App.useApp();
  const query = getBootstrapQuery();
  const app = query.get('app') || '';
  const name = query.get('name') || '';
  const code = query.get('code') || '';

  const { data, loading, error } = useApi(API.streamPlayer, { app, name, code });

  const [playParams, setPlayParams] = useState({
    prefer: 'compat',
    quality: 'auto',
    layout: 1,
  });
  const [playbackResult, setPlaybackResult] = useState(null);
  const [playbackLoading, setPlaybackLoading] = useState(false);
  const [talkbackStatus, setTalkbackStatus] = useState(null);
  const [talkbackSubmitting, setTalkbackSubmitting] = useState(false);

  const payload = data || {};
  const stream = payload.stream || {};
  const playback = payload.playback || {};
  const webrtc = payload.webrtc || {};
  const talkback = payload.talkback || {};
  const talkbackAvailable = Boolean(talkback.available && talkback.stream_code && talkback.session_id);

  useEffect(() => {
    setPlayParams((prev) => ({
      ...prev,
      prefer: playback.recommended_protocol || prev.prefer,
      quality: playback.recommended_quality || prev.quality,
    }));
  }, [playback.recommended_protocol, playback.recommended_quality]);

  const pageTitle = useMemo(() => buildStreamPlayerTitle(stream, app, name, code), [app, code, name, stream]);

  const protocolColumns = [
    {
      title: '协议',
      dataIndex: 'label',
      width: 180,
    },
    {
      title: '地址',
      dataIndex: 'url',
      render: (_value, row) => renderCopyableUrl(row.url),
    },
    {
      title: '动作',
      dataIndex: 'action_href',
      width: 140,
      render: (_value, row) => protocolActionCell(row),
    },
  ];

  const audioColumns = [
    {
      title: '编码',
      dataIndex: 'codec_id_name',
      width: 120,
      render: (value) => value || '-',
    },
    {
      title: '声道',
      dataIndex: 'channels',
      width: 100,
      render: (value) => value || '-',
    },
    {
      title: '采样率',
      dataIndex: 'sample_rate',
      width: 120,
      render: (value) => value ? `${value} Hz` : '-',
    },
    {
      title: '位深',
      dataIndex: 'sample_bit',
      width: 100,
      render: (value) => value ? `${value} bit` : '-',
    },
  ];

  const handleGeneratePlayUrl = useCallback(async () => {
    if (!playback.play_url_endpoint || !stream.app || !stream.name) {
      message.warning('缺少播放地址生成接口或流标识');
      return;
    }

    setPlaybackLoading(true);
    try {
      const res = await apiGetRaw(playback.play_url_endpoint, {
        app: stream.app,
        name: stream.name,
        prefer: playParams.prefer,
        quality: playParams.quality,
        layout: playParams.layout,
      });
      setPlaybackResult(res || null);
      showPlaybackResultMessage(message, res);
    } catch (e) {
      message.error(e?.message || '生成播放地址失败');
    } finally {
      setPlaybackLoading(false);
    }
  }, [message, playParams.layout, playParams.prefer, playParams.quality, playback.play_url_endpoint, stream.app, stream.name]);

  const refreshTalkbackStatus = useCallback(async () => {
    if (!talkbackAvailable) return;
    setTalkbackSubmitting(true);
    try {
      const res = await apiGet(API.talkbackStatus, { session_id: talkback.session_id });
      setTalkbackStatus(res || {});
    } catch (e) {
      message.error(e?.message || '查询回讲状态失败');
    } finally {
      setTalkbackSubmitting(false);
    }
  }, [message, talkback.session_id, talkbackAvailable]);

  const startTalkback = useCallback(async () => {
    if (!talkbackAvailable) return;
    setTalkbackSubmitting(true);
    try {
      const res = await apiPost(API.talkbackStart, {
        stream_code: talkback.stream_code,
        session_id: talkback.session_id,
      });
      setTalkbackStatus(res || {});
      message.success('回讲启动请求已发送');
    } catch (e) {
      message.error(e?.message || '启动回讲失败');
    } finally {
      setTalkbackSubmitting(false);
    }
  }, [message, talkback.session_id, talkback.stream_code, talkbackAvailable]);

  const stopTalkback = useCallback(async () => {
    if (!talkbackAvailable) return;
    setTalkbackSubmitting(true);
    try {
      const res = await apiPost(API.talkbackStop, {
        session_id: talkback.session_id,
      });
      setTalkbackStatus(res || {});
      message.success('回讲停止请求已发送');
    } catch (e) {
      message.error(e?.message || '停止回讲失败');
    } finally {
      setTalkbackSubmitting(false);
    }
  }, [message, talkback.session_id, talkbackAvailable]);

  const playbackUrl = playbackResult?.data?.url || playback.recommended_url || '';
  const playbackStatusText = buildPlaybackStatusText(playbackResult);

  if (loading) {
    return <SkeletonPage />;
  }

  return (
    <div>
      <PageHeader
        title={pageTitle}
        icon={<PlayCircleOutlined />}
        description="视频流实时播放与回放"
        extra={<StreamPlayerHeaderExtra exists={payload.exists} webrtc={webrtc} />}
      />

      {error ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={error.message || '播放器数据加载失败'}
        />
      ) : null}

      {payload.exists === false ? (
        <Alert
          type="info"
          showIcon
          message={payload.message || '请选择一路在线视频流后再进入播放页。'}
        />
      ) : (
        <StreamPlayerContent
          app={app}
          name={name}
          stream={stream}
          playback={playback}
          webrtc={webrtc}
          talkback={talkback}
          talkbackAvailable={talkbackAvailable}
          talkbackStatus={talkbackStatus}
          talkbackSubmitting={talkbackSubmitting}
          playParams={playParams}
          playbackUrl={playbackUrl}
          playbackStatusText={playbackStatusText}
          playbackLoading={playbackLoading}
          protocolColumns={protocolColumns}
          audioColumns={audioColumns}
          onParamsChange={setPlayParams}
          onGeneratePlayUrl={handleGeneratePlayUrl}
          onRefreshTalkback={refreshTalkbackStatus}
          onStartTalkback={startTalkback}
          onStopTalkback={stopTalkback}
        />
      )}
    </div>
  );
}
