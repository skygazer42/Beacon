import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { Descriptions, Timeline, Space, Button, Image, Typography, Divider, App, Modal, Input, Drawer } from 'antd';
import { ClockCircleOutlined, CheckOutlined, CloseOutlined, DownloadOutlined, SearchOutlined, UserOutlined } from '@ant-design/icons';
import DetailDrawer from '../../components/DetailDrawer';
import { WorkflowStatusBadge } from '../../components/StatusBadge';
import { apiGet, apiPost } from '../../api/client';
import { API } from '../../api/endpoints';
import { formatTime } from '../../utils/format';

const { Text, Paragraph } = Typography;

function transitionKey(transition) {
  return transition.id
    || transition.transition_id
    || `${transition.action || transition.label || 'transition'}-${transition.time || transition.created_at || ''}-${transition.operator || ''}`;
}

function noteKey(note) {
  return note.id
    || note.note_id
    || `${note.author || 'note'}-${note.time || note.created_at || ''}-${note.text || note.content || ''}`;
}

function downloadKey(download) {
  return download.id
    || download.url
    || download.name
    || download.label
    || 'download';
}

export default function AlarmDetailDrawer({ open, alarmId, onClose, onAction }) {
  const { message } = App.useApp();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false);
  const [assignTo, setAssignTo] = useState('');
  const [assignNote, setAssignNote] = useState('');
  const [assignSubmitting, setAssignSubmitting] = useState(false);
  const [crossCameraOpen, setCrossCameraOpen] = useState(false);
  const [crossCameraLoading, setCrossCameraLoading] = useState(false);
  const [crossCameraResult, setCrossCameraResult] = useState(null);
  const [crossCameraWindow, setCrossCameraWindow] = useState('30');

  useEffect(() => {
    if (!open || !alarmId) return;
    setLoading(true);
    apiGet(API.alarmDetail, { id: alarmId })
      .then(res => setData(res))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [open, alarmId]);

  const alarm = data?.alarm || {};
  const media = data?.media || {};
  const workflow = data?.workflow || {};
  const navigation = data?.navigation || {};
  const notes = data?.notes || [];
  const metadata = data?.metadata || {};
  const userData = metadata?.user_data || {};
  const downloadsRaw = data?.downloads;
  const downloadsList = Array.isArray(downloadsRaw) ? downloadsRaw : [];
  const downloadsMap = downloadsRaw && typeof downloadsRaw === 'object' && !Array.isArray(downloadsRaw)
    ? downloadsRaw
    : {};

  useEffect(() => {
    if (!open) {
      setAssignOpen(false);
      setAssignTo('');
      setAssignNote('');
      setCrossCameraOpen(false);
      setCrossCameraResult(null);
    }
  }, [open]);

  const assignedToDisplay = workflow.assigned_to || alarm.assigned_to || '';
  const closeHref = navigation.back_href || '/alarms';
  const closeLabel = navigation.back_label || '关闭';

  const handleClose = () => {
    if (typeof onClose === 'function') {
      onClose();
      return;
    }
    globalThis.location.href = closeHref;
  };

  const handleAssignment = async () => {
    const user = assignTo.trim();
    const note = assignNote.trim();
    if (!user && !note) {
      message.warning('请填写分配对象或备注');
      return;
    }
    const payload = { alarm_id: alarmId };
    if (user) payload.assigned_to = user;
    if (note) payload.note = note;
    setAssignSubmitting(true);
    try {
      await apiPost(API.alarmAssignment, payload);
      message.success('分配已更新');
      setAssignOpen(false);
      setAssignTo('');
      setAssignNote('');
      onAction?.();
      const res = await apiGet(API.alarmDetail, { id: alarmId });
      setData(res);
    } catch (e) {
      message.error(e.message || '分配失败');
    } finally {
      setAssignSubmitting(false);
    }
  };

  const handleWorkflow = async (transition) => {
    try {
      const form = new FormData();
      form.append('alarm_ids', String(alarmId));
      form.append('transition', transition);
      await apiPost(API.alarmWorkflow, form);
      message.success('操作成功');
      onAction?.();
      const res = await apiGet(API.alarmDetail, { id: alarmId });
      setData(res);
    } catch (e) {
      message.error(e.message || '操作失败');
    }
  };

  const handleCrossCameraSearch = async () => {
    setCrossCameraLoading(true);
    try {
      const payload = await apiGet(API.alarmCrossCameraSearch, {
        alarm_id: alarmId,
        window_minutes: crossCameraWindow,
        object_code: alarm.object_code || '',
        track_id: userData.track_id || '',
      });
      setCrossCameraResult(payload || null);
    } catch (e) {
      message.error(e?.message || '跨镜头检索失败');
      setCrossCameraResult(null);
    } finally {
      setCrossCameraLoading(false);
    }
  };

  const footer = (
    <>
      <Button icon={<SearchOutlined />} onClick={() => { setCrossCameraOpen(true); handleCrossCameraSearch(); }}>
        跨镜头检索
      </Button>
      <Button icon={<UserOutlined />} onClick={() => {
        setAssignTo(assignedToDisplay);
        setAssignNote('');
        setAssignOpen(true);
      }}
      >
        分配
      </Button>
      {alarm.workflow_status === 'new' && (
        <Button type="primary" icon={<CheckOutlined />} onClick={() => handleWorkflow('acknowledge')}>
          确认告警
        </Button>
      )}
      {(alarm.workflow_status === 'acknowledged' || alarm.workflow_status === 'assigned') && (
        <Button type="primary" onClick={() => handleWorkflow('resolve')}>
          标记解决
        </Button>
      )}
      {alarm.workflow_status !== 'dismissed' && alarm.workflow_status !== 'resolved' && (
        <Button icon={<CloseOutlined />} onClick={() => handleWorkflow('dismiss')}>
          忽略
        </Button>
      )}
      {typeof onClose === 'function' ? (
        <Button onClick={handleClose}>{closeLabel}</Button>
      ) : (
        <Button href={closeHref}>{closeLabel}</Button>
      )}
    </>
  );

  return (
    <DetailDrawer
      open={open}
      onClose={handleClose}
      title={`告警详情 #${alarmId || ''}`}
      width={720}
      loading={loading}
      footer={footer}
    >
      {media.image_url && (
        <div style={{ marginBottom: 16 }}>
          <Image
            src={media.image_url}
            style={{ maxWidth: '100%', maxHeight: 300, objectFit: 'contain', borderRadius: 6 }}
            fallback="data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMzIwIiBoZWlnaHQ9IjIwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMzIwIiBoZWlnaHQ9IjIwMCIgZmlsbD0iI2YwZjBmMCIvPjwvc3ZnPg=="
          />
        </div>
      )}

      {media.video_url && (
        <div style={{ marginBottom: 16 }}>
          <video
            controls
            playsInline
            preload="metadata"
            src={media.video_url}
            style={{ width: '100%', maxHeight: 320, background: '#000', borderRadius: 6 }}
          />
        </div>
      )}

      <Descriptions size="small" bordered column={2} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="告警ID">{alarm.id ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="状态"><WorkflowStatusBadge status={alarm.workflow_status} /></Descriptions.Item>
        <Descriptions.Item label="描述" span={2}>{alarm.desc || '-'}</Descriptions.Item>
        <Descriptions.Item label="视频流">{alarm.stream_name || alarm.stream_code || '-'}</Descriptions.Item>
        <Descriptions.Item label="算法">{alarm.algorithm_code || '-'}</Descriptions.Item>
        <Descriptions.Item label="布控编号">{alarm.control_code || '-'}</Descriptions.Item>
        <Descriptions.Item label="创建时间">{formatTime(alarm.create_time)}</Descriptions.Item>
        <Descriptions.Item label="分配对象" span={2}>{assignedToDisplay || '-'}</Descriptions.Item>
        {alarm.handled_by && (
          <>
            <Descriptions.Item label="处理人">{alarm.handled_by}</Descriptions.Item>
            <Descriptions.Item label="处理时间">{formatTime(alarm.handled_time)}</Descriptions.Item>
          </>
        )}
        {alarm.handled_remark && (
          <Descriptions.Item label="处理备注" span={2}>{alarm.handled_remark}</Descriptions.Item>
        )}
      </Descriptions>

      {workflow.transitions && workflow.transitions.length > 0 && (
        <>
          <Divider style={{ margin: '12px 0' }} />
          <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 14 }}>处理时间线</div>
          <Timeline
            items={workflow.transitions.map((t) => ({
              key: transitionKey(t),
              dot: <ClockCircleOutlined style={{ fontSize: 14 }} />,
              children: (
                <div>
                  <div style={{ fontSize: 13 }}>
                    <Text strong>{t.action || t.label || '-'}</Text>
                    {t.operator && <Text type="secondary"> - {t.operator}</Text>}
                  </div>
                  <Text type="secondary" style={{ fontSize: 12 }}>{formatTime(t.time || t.created_at)}</Text>
                  {t.remark && <div style={{ fontSize: 12, color: '#6b7280' }}>{t.remark}</div>}
                </div>
              ),
            }))}
          />
        </>
      )}

      {notes.length > 0 && (
        <>
          <Divider style={{ margin: '12px 0' }} />
          <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 14 }}>备注</div>
          {notes.map((note) => (
            <div key={noteKey(note)} style={{ padding: '6px 0', borderBottom: '1px solid #f0f0f0', fontSize: 13 }}>
              <Text strong>{note.author || '-'}</Text>
              <Text type="secondary"> - {formatTime(note.time || note.created_at)}</Text>
              <div>{note.text || note.content || '-'}</div>
            </div>
          ))}
        </>
      )}

      {(downloadsList.length > 0 || alarmId) && (
        <>
          <Divider style={{ margin: '12px 0' }} />
          <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 14 }}>导出 / 下载</div>
          <Space wrap>
            {downloadsList.map((d) => (
              <Button key={downloadKey(d)} size="small" icon={<DownloadOutlined />} href={d.url} target="_blank" rel="noreferrer">
                {d.label || d.name || '下载'}
              </Button>
            ))}
            <Button
              size="small"
              icon={<DownloadOutlined />}
              href={downloadsMap.evidence_url || `${API.alarmExportEvidence}?id=${alarmId}`}
              target="_blank"
              rel="noreferrer"
            >
              证据 ZIP
            </Button>
            <Button
              size="small"
              icon={<DownloadOutlined />}
              href={downloadsMap.labelme_url || `${API.alarmExportLabelme}?alarm_ids=${alarmId}`}
              target="_blank"
              rel="noreferrer"
            >
              LabelMe
            </Button>
            <Button
              size="small"
              icon={<DownloadOutlined />}
              href={downloadsMap.coco_url || `${API.alarmExportCoco}?alarm_ids=${alarmId}`}
              target="_blank"
              rel="noreferrer"
            >
              COCO
            </Button>
          </Space>
        </>
      )}

      <Modal
        title="分配告警"
        open={assignOpen}
        onOk={handleAssignment}
        onCancel={() => { setAssignOpen(false); setAssignNote(''); }}
        confirmLoading={assignSubmitting}
        okText="提交"
      >
        <div style={{ marginBottom: 8, fontSize: 13, color: '#64748b' }}>
          当前分配：{assignedToDisplay || '—'}
        </div>
        <div style={{ marginBottom: 6, fontSize: 13 }}>分配给（用户名或标识）</div>
        <Input
          value={assignTo}
          onChange={(e) => setAssignTo(e.target.value)}
          placeholder="assigned_to"
          style={{ marginBottom: 12 }}
        />
        <div style={{ marginBottom: 6, fontSize: 13 }}>备注（将追加到告警备注）</div>
        <Input.TextArea value={assignNote} onChange={(e) => setAssignNote(e.target.value)} rows={3} placeholder="可选" />
      </Modal>

      <Drawer
        title={<span id="crossCameraSearchTitle">跨镜头检索</span>}
        aria-labelledby="crossCameraSearchTitle"
        open={crossCameraOpen}
        onClose={() => setCrossCameraOpen(false)}
        width={720}
        destroyOnHidden={false}
        footer={(
          <div style={{ textAlign: 'right' }}>
            <Space>
              <Button onClick={() => setCrossCameraOpen(false)}>
                关闭
              </Button>
              <Button type="primary" loading={crossCameraLoading} onClick={handleCrossCameraSearch}>
                重新检索
              </Button>
            </Space>
          </div>
        )}
      >
        <div style={{ marginBottom: 12 }}>
          <label htmlFor="crossCameraWindow" style={{ display: 'block', marginBottom: 6, fontSize: 13 }}>
            时间窗口（分钟）
          </label>
          <Input
            id="crossCameraWindow"
            value={crossCameraWindow}
            onChange={(e) => setCrossCameraWindow(e.target.value)}
            style={{ maxWidth: 180 }}
          />
        </div>
        {crossCameraResult ? (
          <div>
            <div style={{ marginBottom: 8, color: '#64748b', fontSize: 13 }}>
              匹配结果：{crossCameraResult.total ?? 0}
            </div>
            {Array.isArray(crossCameraResult.items) && crossCameraResult.items.length > 0 ? (
              <div style={{ display: 'grid', gap: 8 }}>
                {crossCameraResult.items.map((item) => (
                  <div
                    key={item.id}
                    style={{
                      border: '1px solid #e5e7eb',
                      borderRadius: 8,
                      padding: 12,
                      background: '#fafafa',
                    }}
                  >
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{item.stream_name || item.stream_code || `告警 #${item.id}`}</div>
                    <div style={{ marginTop: 4, fontSize: 12, color: '#6b7280' }}>
                      {item.control_code || '-'} · {formatTime(item.create_time)}
                    </div>
                    {item.match_reason ? (
                      <div style={{ marginTop: 6, fontSize: 12 }}>{item.match_reason}</div>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ color: '#8c8c8c', fontSize: 12 }}>暂无跨镜头匹配结果</div>
            )}
          </div>
        ) : null}
      </Drawer>
    </DetailDrawer>
  );
}

AlarmDetailDrawer.propTypes = {
  open: PropTypes.bool,
  alarmId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  onClose: PropTypes.func,
  onAction: PropTypes.func,
};
