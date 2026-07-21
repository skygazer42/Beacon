import React, { useCallback, useState } from 'react';
import { App, Button, Input, Modal, Space, Tag, Typography } from 'antd';
import { ExperimentOutlined } from '@ant-design/icons';
import SkeletonPage from '../../components/Skeleton';
import PageHeader from '../../components/PageHeader';
import ProTable from '../../components/ProTable';
import KpiCard, { KpiCardGroup } from '../../components/KpiCard';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { apiPost } from '../../api/client';
import { getBootstrapQuery } from '../../bootstrap';
import { formatTime } from '../../utils/format';

const { Text } = Typography;

export default function AlgorithmVersionsPage() {
  const { message } = App.useApp();
  const query = getBootstrapQuery();
  const code = query.get('code') || '';
  const { data, loading, run } = useApi(API.algorithmVersions, { code });
  const [grayOpen, setGrayOpen] = useState(false);
  const [grayRow, setGrayRow] = useState(null);
  const [grayCodes, setGrayCodes] = useState('');

  const algorithm = data?.algorithm || {};
  const summary = data?.summary || {};
  const rows = data?.versions || [];

  const reload = useCallback(() => run({ code }), [run, code]);

  const postAlgo = async (url, body, okMsg) => {
    try {
      await apiPost(url, body);
      message.success(okMsg || '操作成功');
      reload();
    } catch (e) {
      message.error(e.message || '操作失败');
    }
  };

  const columns = [
    { title: '版本号', dataIndex: 'version_no', width: 80 },
    { title: '版本名称', dataIndex: 'version_name', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'state_label',
      width: 100,
      render: (value, row) => {
        if (row.is_current) return <Tag color="success">{value || '当前版本'}</Tag>;
        if (row.is_gray) return <Tag color="warning">{value || '灰度版本'}</Tag>;
        return <Tag>{value || '历史版本'}</Tag>;
      },
    },
    {
      title: '来源',
      dataIndex: 'source_label',
      width: 90,
      render: (value) => value || '-',
    },
    {
      title: '配置摘要',
      dataIndex: 'config_summary',
      ellipsis: true,
      render: (value) => value || '-',
    },
    {
      title: '灰度布控',
      dataIndex: 'gray_control_codes',
      ellipsis: true,
      render: (value) => value || '-',
    },
    { title: '备注', dataIndex: 'note', width: 180, ellipsis: true },
    {
      title: '激活时间',
      dataIndex: 'activated_at',
      width: 160,
      render: (v) => <Text type="secondary" style={{ fontSize: 12 }}>{formatTime(v)}</Text>,
    },
    {
      title: '操作',
      key: 'ops',
      width: 280,
      fixed: 'right',
      render: (_, r) => (
        <Space size={0} wrap>
          <Button
            type="link"
            size="small"
            disabled={!code || !r.id}
            onClick={() => postAlgo(API.algorithmVersionActivate, { code, version_id: String(r.id) }, '已激活')}
          >
            激活
          </Button>
          <Button type="link" size="small" onClick={() => postAlgo(API.algorithmVersionRollback, { code }, '已回滚')}>
            回滚
          </Button>
          <Button
            type="link"
            size="small"
            onClick={() => {
              setGrayRow(r);
              setGrayCodes((r.gray_control_codes || '').trim());
              setGrayOpen(true);
            }}
          >
            灰度
          </Button>
          <Button
            type="link"
            size="small"
            onClick={() => postAlgo(API.algorithmAnalyzerLoad, { code, device: 'CPU' }, '加载请求已发送')}
          >
            加载
          </Button>
          <Button
            type="link"
            size="small"
            onClick={() => postAlgo(API.algorithmAnalyzerUnload, { code, device: 'CPU' }, '卸载请求已发送')}
          >
            卸载
          </Button>
        </Space>
      ),
    },
  ];

  if (loading && !data) {
    return <SkeletonPage />;
  }

  return (
    <div>
      <PageHeader
        title={`算法版本 - ${algorithm.name || code}`}
        icon={<ExperimentOutlined />}
        description="算法版本历史管理"
        extra={<Button href="/algorithm/index">返回列表</Button>}
      />
      {code ? null : <Text type="danger">缺少算法 code 参数</Text>}
      {code ? (
        <KpiCardGroup>
          <KpiCard title="版本总数" value={summary.version_count ?? rows.length} icon={<ExperimentOutlined />} />
          <KpiCard title="当前版本" value={summary.current_version_name || '-'} color="#16a34a" />
          <KpiCard title="灰度版本" value={summary.gray_version_name || '-'} color="#fa8c16" />
          <KpiCard title="算法来源" value={algorithm.source_label || '-'} color="#2563eb" />
        </KpiCardGroup>
      ) : null}
      <ProTable
        columns={columns}
        dataSource={rows}
        loading={loading}
        rowKey={(r) => String(r.id ?? r.version_no)}
        pagination={false}
      />
      <Modal
        title="设置灰度版本"
        open={grayOpen}
        onCancel={() => setGrayOpen(false)}
        cancelText="取消"
        onOk={async () => {
          if (!grayRow) return;
          try {
            await apiPost(API.algorithmVersionGray, {
              code,
              version_id: String(grayRow.id),
              gray_control_codes: grayCodes.trim(),
            });
            message.success('灰度已更新');
            setGrayOpen(false);
            reload();
          } catch (e) {
            message.error(e.message || '失败');
          }
        }}
        okText="确定"
        destroyOnHidden
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
          灰度布控编号列表（逗号分隔）；留空可清空灰度。
        </Text>
        <Input.TextArea rows={3} value={grayCodes} onChange={(e) => setGrayCodes(e.target.value)} placeholder="ctrl1,ctrl2" />
      </Modal>
    </div>
  );
}
