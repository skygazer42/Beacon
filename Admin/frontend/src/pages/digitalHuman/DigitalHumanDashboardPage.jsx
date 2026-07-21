import React from 'react';
import { Alert, Button, Card, Progress, Space, Tag, Typography } from 'antd';
import {
  AlertOutlined,
  AppstoreOutlined,
  DeploymentUnitOutlined,
  DesktopOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import SummaryCard, { PanelTitle } from '../../components/SummaryCard';
import KpiCard, { KpiCardGroup } from '../../components/KpiCard';
import SkeletonPage from '../../components/Skeleton';
import useDigitalHumanResource from './useDigitalHumanResource';
import { getDigitalHumanDashboard } from './dataAdapter';
import './digitalHumanStyles.css';

const { Text } = Typography;

function levelTag(level) {
  if (level === 'critical') return <Tag color="error">严重</Tag>;
  if (level === 'warning') return <Tag color="warning">警告</Tag>;
  return <Tag color="processing">提示</Tag>;
}

export default function DigitalHumanDashboardPage() {
  const { data, loading, error, reload } = useDigitalHumanResource(getDigitalHumanDashboard, []);

  if (loading && !data) {
    return <SkeletonPage kpiCount={4} />;
  }

  if (error && !data) {
    return <Alert type="warning" showIcon message={error.message || '数字人监管大盘加载失败'} />;
  }

  if (!data) {
    return <Alert type="warning" showIcon message="数字人监管大盘暂无数据" />;
  }

  const summaryItems = [
    { label: '更新时间', value: data.generatedAt },
    { label: '推送路由', value: data.routingHealth.enabled ? `已启用 / ${data.routingHealth.activeRoutes} 条生效` : '未启用' },
    { label: '数据策略', value: 'Beacon 本地数字人真数据' },
    { label: '工作区', value: '概览 / 终端 / 告警 / 日志' },
  ];

  return (
    <div className="beacon-dh-page">
      <PageHeader
        title="数字人监管"
        icon={<AppstoreOutlined />}
        description="统一查看数字人终端、告警与监管日志。"
        extra={(
          <Space wrap>
            <Button href="/digital-human/device-monitor">终端</Button>
            <Button href="/digital-human/alert-center">告警</Button>
            <Button href="/digital-human/monitor-logs">日志</Button>
            <Button href="/digital-human/system-settings">设置</Button>
            <Button icon={<ReloadOutlined />} onClick={() => reload()}>刷新</Button>
          </Space>
        )}
      />

      <KpiCardGroup>
        {data.kpis.map((item) => (
          <KpiCard
            key={item.title}
            title={item.title}
            value={item.value}
            suffix={item.suffix}
            color={item.color}
            icon={<DesktopOutlined />}
            metaItems={item.metaItems}
          />
        ))}
      </KpiCardGroup>

      <div className="beacon-dh-grid beacon-dh-grid--two">
        <Card
          className="beacon-panel-card beacon-panel-card--tone-blue"
          size="small"
          title={<PanelTitle title="近 7 日趋势" meta="在线终端 / 告警 / 严重告警" icon={<DeploymentUnitOutlined />} tone="blue" />}
        >
          <div className="beacon-dh-bar-list">
            {data.trendRows.map((row) => (
              <div className="beacon-dh-bar-row" key={row.label}>
                <div className="beacon-dh-bar-row__label">{row.label}</div>
                <div className="beacon-dh-bar-row__metric">
                  <div className="beacon-dh-bar-row__metric-head">
                    <span>在线终端</span>
                    <strong>{row.online}</strong>
                  </div>
                  <Progress percent={Math.min(row.online * 4, 100)} size="small" showInfo={false} strokeColor="#2563eb" />
                </div>
                <div className="beacon-dh-bar-row__metric">
                  <div className="beacon-dh-bar-row__metric-head">
                    <span>告警数</span>
                    <strong>{row.alerts}</strong>
                  </div>
                  <Progress percent={Math.min(row.alerts * 14, 100)} size="small" showInfo={false} strokeColor="#f97316" />
                </div>
                <div className="beacon-dh-bar-row__metric">
                  <div className="beacon-dh-bar-row__metric-head">
                    <span>严重告警</span>
                    <strong>{row.critical}</strong>
                  </div>
                  <Progress percent={Math.min(row.critical * 34, 100)} size="small" showInfo={false} strokeColor="#ef4444" />
                </div>
              </div>
            ))}
          </div>
        </Card>

        <SummaryCard
          title="接入说明"
          meta="首期前端接入边界"
          icon={<DesktopOutlined />}
          tone="cyan"
          items={summaryItems}
          bodyStyle={{ padding: '16px 18px' }}
        />
      </div>

      <div className="beacon-dh-grid beacon-dh-grid--two">
        <Card
          className="beacon-panel-card beacon-panel-card--tone-slate"
          size="small"
          title={<PanelTitle title="设备负载预警" meta="按 CPU / 内存 / GPU 最大值排序" icon={<DesktopOutlined />} tone="slate" />}
          extra={<a href="/digital-human/device-monitor">查看全部</a>}
        >
          <div className="beacon-dh-bar-list">
            {data.topLoads.map((item) => (
              <div className="beacon-dh-load-row" key={item.id}>
                <div>
                  <div className="beacon-dh-load-row__title">{item.name}</div>
                  <div className="beacon-dh-load-row__meta">
                    {item.deviceCode} · {item.region}
                  </div>
                  <Progress
                    percent={item.maxLoad}
                    size="small"
                    showInfo={false}
                    strokeColor={item.maxLoad >= 85 ? '#ef4444' : item.maxLoad >= 70 ? '#f97316' : '#2563eb'}
                    style={{ marginTop: 8 }}
                  />
                </div>
                <div className="beacon-dh-load-row__value">
                  {item.maxLoad}%
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card
          className="beacon-panel-card beacon-panel-card--tone-orange"
          size="small"
          title={<PanelTitle title="预警播报" meta="最近活跃数字人告警" icon={<AlertOutlined />} tone="orange" />}
          extra={<a href="/digital-human/alert-center">告警中心</a>}
        >
          <div className="beacon-dh-feed">
            {data.alertFeed.map((item) => (
              <div className="beacon-dh-feed__item" key={item.id}>
                <span className={`beacon-dh-feed__dot beacon-dh-feed__dot--${item.level}`} />
                <div>
                  <div className="beacon-dh-feed__title">
                    <Space size={8} wrap>
                      <span>{item.title}</span>
                      {levelTag(item.level)}
                    </Space>
                  </div>
                  <div className="beacon-dh-feed__meta">
                    {item.deviceName} · {item.region} · {item.lastOccurredAt}
                  </div>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {item.description}
                  </Text>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
