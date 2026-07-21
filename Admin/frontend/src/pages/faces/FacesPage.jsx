import React, { useCallback, useEffect, useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Modal,
  Pagination,
  Popconfirm,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import {
  ApiOutlined,
  CheckCircleOutlined,
  DatabaseOutlined,
  EyeOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  SettingOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import ProTable from '../../components/ProTable';
import { PanelTitle } from '../../components/SummaryCard';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { apiPost } from '../../api/client';
import { formatTime } from '../../utils/format';
import './FacesPage.css';

const { Text } = Typography;

function normalizeFallbackRows(faceDb) {
  if (!faceDb) return [];
  if (Array.isArray(faceDb)) {
    return faceDb.map((row, i) => ({ ...row, _rowKey: row.id ?? row.code ?? i }));
  }
  if (Array.isArray(faceDb.faces)) {
    return faceDb.faces.map((row, i) => ({ ...row, _rowKey: row.id ?? row.face_id ?? i }));
  }
  if (Array.isArray(faceDb.list)) {
    return faceDb.list.map((row, i) => ({ ...row, _rowKey: row.id ?? i }));
  }
  if (Array.isArray(faceDb.items)) {
    return faceDb.items.map((row, i) => ({ ...row, _rowKey: row.id ?? i }));
  }
  if (typeof faceDb === 'object') {
    const out = [];
    Object.entries(faceDb).forEach(([libKey, val]) => {
      if (val == null || typeof val !== 'object') {
        out.push({ library: libKey, value: String(val), _rowKey: libKey });
        return;
      }
      if (Array.isArray(val)) {
        val.forEach((item, i) => {
          out.push({
            library: libKey,
            ...(typeof item === 'object' ? item : { value: String(item) }),
            _rowKey: `${libKey}-${i}`,
          });
        });
        return;
      }
      out.push({ library: libKey, ...val, _rowKey: libKey });
    });
    return out;
  }
  return [];
}

function parseJsonField(value, label) {
  const text = String(value || '').trim();
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`${label} 不是合法 JSON`);
  }
}

function formatSearchState(searchEnabled, labels = {}) {
  if (searchEnabled == null) {
    return labels.unknown || '未知';
  }
  return searchEnabled ? labels.enabled || '已启用' : labels.disabled || '已停用';
}

function resolveDataSourceLabel(directError, fallbackRowCount) {
  if (!directError) {
    return '直连人脸库';
  }
  return fallbackRowCount > 0 ? 'Analyzer 回退数据' : '仅元信息';
}

function readPathValue(source, path) {
  if (!source || !path) return undefined;
  return String(path)
    .split('.')
    .reduce((current, key) => (current == null ? undefined : current[key]), source);
}

function hasMeaningfulValue(value) {
  if (value === null || value === undefined) return false;
  if (typeof value === 'string') return value.trim() !== '';
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === 'object') return Object.keys(value).length > 0;
  return true;
}

function firstNonEmpty(source, keys) {
  for (const key of keys) {
    const value = readPathValue(source, key);
    if (hasMeaningfulValue(value)) {
      return value;
    }
  }
  return undefined;
}

function stringifyCellValue(value) {
  if (value === null || value === undefined || value === '') return '';
  if (Array.isArray(value)) {
    return value
      .map((item) => stringifyCellValue(item))
      .filter(Boolean)
      .join(', ');
  }
  if (typeof value === 'object') {
    const simpleText = firstNonEmpty(value, ['label', 'name', 'title', 'value', 'id']);
    if (typeof simpleText === 'string' || typeof simpleText === 'number') {
      return String(simpleText);
    }
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function normalizeStringArray(value) {
  if (!hasMeaningfulValue(value)) return [];
  if (Array.isArray(value)) {
    return value.flatMap((item) => normalizeStringArray(item));
  }
  if (typeof value === 'object') {
    return Object.values(value).flatMap((item) => normalizeStringArray(item));
  }
  const text = String(value).trim();
  if (!text) return [];
  if ((text.startsWith('[') && text.endsWith(']')) || (text.startsWith('{') && text.endsWith('}'))) {
    try {
      const parsed = JSON.parse(text);
      return normalizeStringArray(parsed);
    } catch {
      // fall through to raw text
    }
  }
  return text
    .split(/[,，、;；|/]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function extractFaceId(row) {
  return stringifyCellValue(firstNonEmpty(row, ['id', 'face_id', 'faceId', 'code', 'uuid']));
}

function extractFaceName(row) {
  return stringifyCellValue(firstNonEmpty(row, ['name', 'nickname', 'display_name', 'displayName', 'person_name', 'personName']));
}

function extractFaceGroup(row) {
  return stringifyCellValue(firstNonEmpty(row, ['group_name', 'groupName', 'group', 'face_group', 'faceGroup', 'library', 'lib', 'app', 'collection']));
}

function extractFaceTags(row) {
  const tagValue = firstNonEmpty(row, [
    'tags',
    'tag',
    'labels',
    'label',
    'tag_list',
    'tagList',
    'meta.tags',
    'extra.tags',
  ]);
  return Array.from(new Set(normalizeStringArray(tagValue)));
}

function extractFaceAlgorithm(row) {
  return stringifyCellValue(firstNonEmpty(row, [
    'featureAlgorithmCode',
    'feature_algorithm_code',
    'featureAlgorithm',
    'feature_algorithm',
    'algorithm',
    'algo',
    'model',
  ]));
}

function extractFaceEnabled(row) {
  const raw = firstNonEmpty(row, ['enabled', 'searchEnabled', 'status.enabled']);
  if (typeof raw === 'boolean') return raw;
  if (typeof raw === 'number') return raw > 0;
  if (typeof raw === 'string') {
    const normalized = raw.trim().toLowerCase();
    if (['true', '1', 'enabled', 'enable', 'on', 'active'].includes(normalized)) return true;
    if (['false', '0', 'disabled', 'disable', 'off', 'inactive'].includes(normalized)) return false;
  }
  return null;
}

function extractCreatedAt(row) {
  return firstNonEmpty(row, ['createdAtMs', 'created_at', 'createdAt', 'create_time', 'createTime', 'ctime']);
}

function extractUpdatedAt(row) {
  return firstNonEmpty(row, ['updatedAtMs', 'updated_at', 'updatedAt', 'update_time', 'updateTime', 'mtime']);
}

function formatFaceTime(value) {
  return hasMeaningfulValue(value) ? formatTime(value) : '-';
}

function buildFaceSearchText(row) {
  return [
    extractFaceId(row),
    extractFaceName(row),
    extractFaceGroup(row),
    extractFaceAlgorithm(row),
    extractFaceTags(row).join(' '),
    stringifyCellValue(firstNonEmpty(row, ['remark', 'description', 'note'])),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

function buildFaceErrorInsight({ error, directError, fallbackError, fallbackRowsCount }) {
  const details = [
    error?.message ? { source: '页面兼容接口', message: error.message } : null,
    directError?.message ? { source: '直连人脸库', message: directError.message } : null,
    fallbackError ? { source: 'Analyzer 回退接口', message: fallbackError } : null,
  ].filter(Boolean);

  const primary = details[0] || null;
  if (!primary) {
    return {
      hasIssue: false,
      severity: 'success',
      statusLabel: '服务可用',
      sourceLabel: '直连人脸库',
      hostPort: '-',
      endpoint: API.faceList,
      fallbackState: fallbackRowsCount ? '已装载回退数据' : '未使用回退数据',
      hint: '当前可以直接从人脸库接口读取列表并执行新增、删除和相似搜索。',
      summary: '人脸库列表直连正常，页面展示的数据与操作都来自实时接口。',
      rawDetail: '',
      details: [],
    };
  }

  const message = primary.message || '';
  const hostMatch = message.match(/host='([^']+)', port=(\d+)/);
  const endpointMatch = message.match(/url:\s*([^\s)]+)/);
  let hint = '请检查 Analyzer 人脸服务与管理端之间的接口连通性。';

  if (/Connection refused/i.test(message)) {
    hint = 'Analyzer 人脸服务未启动，或 127.0.0.1:9993 端口当前不可达。';
  } else if (/Max retries exceeded/i.test(message)) {
    hint = '管理端已多次重试直连接口，但目标服务没有返回可用结果。';
  } else if (/timed out/i.test(message)) {
    hint = '直连接口响应超时，请检查服务负载、网络或模型进程状态。';
  }

  return {
    hasIssue: true,
    severity: error?.message ? 'error' : 'warning',
    statusLabel: '接口异常',
    sourceLabel: primary.source,
    hostPort: hostMatch ? `${hostMatch[1]}:${hostMatch[2]}` : '-',
    endpoint: endpointMatch?.[1] || API.faceList,
    fallbackState: fallbackRowsCount ? '已切换兼容回退数据' : '没有可用回退数据',
    hint,
    summary: fallbackRowsCount
      ? `当前无法从${primary.source}读取人脸库列表，页面已切换为兼容回退展示。`
      : `当前无法从${primary.source}读取人脸库列表，页面没有可用的人脸条目回退数据。`,
    rawDetail: details
      .map((item) => `${item.source}\n${item.message}`)
      .join('\n\n'),
    details,
  };
}

function buildFaceActionBody(values, { includeMinScore = false } = {}) {
  const body = {};
  const embedding = parseJsonField(values.embedding_json, 'Embedding JSON');
  if (embedding !== undefined) {
    body.embedding = embedding;
  }
  const imageBase64 = String(values.image_base64 || '').trim();
  if (imageBase64) {
    body.image_base64 = imageBase64;
  }
  const featureAlgorithmCode = String(values.featureAlgorithmCode || '').trim();
  if (featureAlgorithmCode) {
    body.featureAlgorithmCode = featureAlgorithmCode;
  }
  if (includeMinScore && values.minScore !== undefined && values.minScore !== null && values.minScore !== '') {
    body.minScore = Number(values.minScore);
  }
  return body;
}

function hasFaceVectorSource(body) {
  return Boolean(body.embedding || body.image_base64);
}

function buildFaceGroupOptions(rows) {
  const unique = Array.from(
    new Set(
      rows
        .map((row) => extractFaceGroup(row))
        .filter(Boolean),
    ),
  );
  return unique.map((value) => ({ value, label: value }));
}

function filterFaceRows(rows, { tableQuery, groupFilter }) {
  const keyword = tableQuery.trim().toLowerCase();
  return rows.filter((row) => {
    const group = extractFaceGroup(row);
    const matchesGroup = !groupFilter || group === groupFilter;
    const matchesQuery = !keyword || buildFaceSearchText(row).includes(keyword);
    return matchesGroup && matchesQuery;
  });
}

function buildFaceOverviewMetrics({ rows, directError, directMeta, groupOptions }) {
  const rowsWithEnabledState = rows.filter((row) => extractFaceEnabled(row) !== null);
  const enabledRows = rowsWithEnabledState.filter((row) => extractFaceEnabled(row) === true).length;
  return [
    {
      key: 'count',
      label: '当前条目',
      value: String(directError ? rows.length : directMeta.count ?? rows.length ?? 0),
      note: directError ? '回退视图' : '实时列表',
    },
    {
      key: 'groups',
      label: '分组数量',
      value: String(groupOptions.length),
      note: '本页可筛选',
    },
    {
      key: 'enabled',
      label: '启用记录',
      value: rowsWithEnabledState.length ? String(enabledRows) : '-',
      note: rowsWithEnabledState.length
        ? `占已返回状态 ${Math.round((enabledRows / rowsWithEnabledState.length) * 100)}%`
        : '接口未返回状态字段',
    },
    {
      key: 'dim',
      label: '特征维度',
      value: String(directMeta.dim ?? '-'),
      note: '直连接口返回',
    },
  ];
}

function buildFaceOverviewFacts({ data, directError, fallbackRows, searchEnabled }) {
  const defaultAlgorithm = data?.default_feature_algorithm_label || data?.default_feature_algorithm_code || '未配置';
  const searchStatus = formatSearchState(searchEnabled);
  const dataSource = resolveDataSourceLabel(directError, fallbackRows.length);
  return [
    { key: 'algorithm', label: '默认算法', value: defaultAlgorithm },
    { key: 'tracking', label: '跟踪算法数', value: String(data?.tracking_algorithms?.length ?? 0) },
    { key: 'search', label: '搜索状态', value: searchStatus },
    { key: 'source', label: '当前数据源', value: dataSource },
  ];
}

function buildFaceColumns(handleDelete) {
  return [
    {
      title: '人脸ID',
      key: 'faceId',
      width: 180,
      render: (_, row) => {
        const faceId = extractFaceId(row);
        const library = stringifyCellValue(firstNonEmpty(row, ['library', 'lib', 'collection']));
        return (
          <div className="beacon-faces-table-cell">
            <div className="beacon-faces-table-cell__primary">{faceId || '-'}</div>
            {library ? <div className="beacon-faces-table-cell__secondary">{library}</div> : null}
          </div>
        );
      },
    },
    {
      title: '人脸名称',
      key: 'faceName',
      width: 260,
      render: (_, row) => {
        const name = extractFaceName(row);
        const enabled = extractFaceEnabled(row);
        const tags = extractFaceTags(row);
        return (
          <div className="beacon-faces-table-cell">
            <div className="beacon-faces-table-cell__headline">
              <span className="beacon-faces-table-cell__primary">{name || '-'}</span>
              {enabled == null ? null : (
                <Tag color={enabled ? 'success' : 'default'}>
                  {enabled ? '启用' : '停用'}
                </Tag>
              )}
            </div>
            {tags.length ? (
              <div className="beacon-faces-table-tags">
                {tags.slice(0, 3).map((tag) => (
                  <Tag key={`${extractFaceId(row)}-${tag}`}>{tag}</Tag>
                ))}
                {tags.length > 3 ? <span className="beacon-faces-table-cell__secondary">+{tags.length - 3}</span> : null}
              </div>
            ) : (
              <div className="beacon-faces-table-cell__secondary">未配置标签</div>
            )}
          </div>
        );
      },
    },
    {
      title: '分组',
      key: 'group',
      width: 150,
      render: (_, row) => extractFaceGroup(row) || '-',
    },
    {
      title: '标签',
      key: 'tags',
      width: 220,
      render: (_, row) => {
        const tags = extractFaceTags(row);
        return tags.length ? tags.join(' / ') : '-';
      },
    },
    {
      title: '特征算法',
      key: 'algorithm',
      width: 180,
      render: (_, row) => extractFaceAlgorithm(row) || '-',
    },
    {
      title: '创建时间',
      key: 'createdAt',
      width: 170,
      render: (_, row) => formatFaceTime(extractCreatedAt(row)),
    },
    {
      title: '更新时间',
      key: 'updatedAt',
      width: 170,
      render: (_, row) => formatFaceTime(extractUpdatedAt(row)),
    },
    {
      title: '操作',
      key: 'actions',
      width: 100,
      fixed: 'right',
      render: (_, row) => {
        const faceId = row.id || row.face_id;
        return faceId ? (
          <Popconfirm title="确认删除这条人脸记录？" onConfirm={() => handleDelete(faceId)}>
            <Button type="link" size="small" danger>
              删除
            </Button>
          </Popconfirm>
        ) : (
          '-'
        );
      },
    },
  ];
}

function FacesHeader({ searchEnabled, directLoading, onReload, onToggle, onAdd, onSearch }) {
  return (
    <PageHeader
      title="人脸库"
      icon={<EyeOutlined />}
      description="人脸库管理与相似搜索工作台"
      extra={(
        <div className="beacon-faces-toolbar">
          <Button icon={<ReloadOutlined />} onClick={onReload}>
            刷新
          </Button>
          <Button onClick={onToggle} disabled={directLoading}>
            {searchEnabled ? '停用搜索' : '启用搜索'}
          </Button>
          <Button icon={<PlusOutlined />} onClick={onAdd}>
            新增人脸
          </Button>
          <Button type="primary" icon={<SearchOutlined />} onClick={onSearch}>
            相似搜索
          </Button>
        </div>
      )}
    />
  );
}

function FacesIssueAlert({ errorInsight, fallbackRowsCount, onOpenDetail }) {
  if (!errorInsight.hasIssue) {
    return null;
  }
  return (
    <Alert
      className="beacon-faces-alert"
      type={errorInsight.severity}
      showIcon
      message={errorInsight.hostPort === '-' ? `${errorInsight.sourceLabel}异常` : `${errorInsight.hostPort} 直连接口不可用`}
      description={(
        <div className="beacon-faces-alert__body">
          <span>{fallbackRowsCount ? '页面已切换为兼容回退数据。' : '当前没有可用回退数据，列表暂时为空。'}</span>
        </div>
      )}
      action={(
        <Button type="link" size="small" onClick={onOpenDetail}>
          查看原始错误
        </Button>
      )}
    />
  );
}

function FacesOverviewCard({ overviewMetrics, overviewFacts, directError }) {
  return (
    <Card
      className="beacon-panel-card beacon-panel-card--tone-blue beacon-faces-overview-card"
      size="small"
      title={<PanelTitle title="库统计概览" meta="直连状态 / 检索能力 / 当前规模" icon={<DatabaseOutlined />} tone="blue" />}
      extra={<Tag color={directError ? 'warning' : 'processing'}>{directError ? '回退模式' : '直连模式'}</Tag>}
      styles={{ body: { padding: '12px 14px' } }}
    >
      <div className="beacon-faces-metric-grid">
        {overviewMetrics.map((item) => (
          <div className="beacon-faces-metric" key={item.key}>
            <span className="beacon-faces-metric__label">{item.label}</span>
            <span className="beacon-faces-metric__value">{item.value}</span>
            <span className="beacon-faces-metric__note">{item.note}</span>
          </div>
        ))}
      </div>
      <div className="beacon-faces-facts">
        {overviewFacts.map((item) => (
          <div className="beacon-faces-facts__item" key={item.key}>
            <span className="beacon-faces-facts__label">{item.label}</span>
            <span className="beacon-faces-facts__value">{item.value}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function FacesErrorCard({ errorInsight, errorSummaryItems, fallbackRowsCount, onOpenDetail }) {
  return (
    <Card
      className={`beacon-panel-card ${errorInsight.hasIssue ? 'beacon-panel-card--tone-orange' : 'beacon-panel-card--tone-green'} beacon-faces-error-card`}
      size="small"
      title={<PanelTitle title="错误分析" meta="接口 / 回退 / 目标地址" icon={errorInsight.hasIssue ? <WarningOutlined /> : <CheckCircleOutlined />} tone={errorInsight.hasIssue ? 'orange' : 'green'} />}
      extra={(
        <span className={`beacon-faces-error-card__status beacon-faces-error-card__status--${errorInsight.hasIssue ? 'warning' : 'healthy'}`}>
          {errorInsight.statusLabel}
        </span>
      )}
      styles={{ body: { padding: '12px 14px' } }}
    >
      <div className="beacon-faces-facts beacon-faces-facts--diagnostics">
        {errorSummaryItems.map((item) => (
          <div className="beacon-faces-facts__item" key={item.key}>
            <span className="beacon-faces-facts__label">{item.label}</span>
            <span className="beacon-faces-facts__value">{item.value}</span>
          </div>
        ))}
      </div>
      {errorInsight.hasIssue ? (
        <div className="beacon-faces-error-card__footer">
          <Text type="secondary">
            {fallbackRowsCount ? '当前已降级为回退视图。' : '当前列表为空，等待直连服务恢复。'}
          </Text>
          <Button type="link" size="small" className="beacon-faces-error-card__link" onClick={onOpenDetail}>
            查看原始错误
          </Button>
        </div>
      ) : (
        <div className="beacon-faces-error-card__message beacon-faces-error-card__message--healthy">
          <div className="beacon-faces-error-card__message-title">接口状态</div>
          <div className="beacon-faces-error-card__message-copy">{errorInsight.summary}</div>
        </div>
      )}
    </Card>
  );
}

function FacesTopGrid({ overviewMetrics, overviewFacts, directError, errorInsight, errorSummaryItems, fallbackRowsCount, onOpenDetail }) {
  return (
    <div className="beacon-faces-top-grid" data-testid="faces-top-grid">
      <FacesOverviewCard
        overviewMetrics={overviewMetrics}
        overviewFacts={overviewFacts}
        directError={directError}
      />
      <FacesErrorCard
        errorInsight={errorInsight}
        errorSummaryItems={errorSummaryItems}
        fallbackRowsCount={fallbackRowsCount}
        onOpenDetail={onOpenDetail}
      />
    </div>
  );
}

function FacesWorkspaceCard({
  filteredRows,
  rows,
  searchEnabled,
  tableQuery,
  groupFilter,
  groupOptions,
  columns,
  pagedRows,
  showInlineLoading,
  currentPage,
  totalPages,
  tablePagination,
  onTableQueryChange,
  onGroupFilterChange,
  onResetFilters,
  onPaginationChange,
}) {
  return (
    <Card
      className="beacon-panel-card beacon-panel-card--tone-slate beacon-faces-workspace-card"
      size="small"
      title={<PanelTitle title="人脸库条目" meta="本地筛选 / 删除 / 相似搜索联动" icon={<ApiOutlined />} tone="slate" />}
      extra={(
        <div className="beacon-faces-workspace-meta">
          <span className="beacon-faces-workspace-meta__pill beacon-faces-workspace-meta__pill--blue">当前 {filteredRows.length}</span>
          <span className="beacon-faces-workspace-meta__pill">{rows.length} 条结果</span>
          <span className={`beacon-faces-workspace-meta__pill ${searchEnabled ? 'beacon-faces-workspace-meta__pill--green' : ''}`}>
            {formatSearchState(searchEnabled, {
              unknown: '搜索状态未知',
              enabled: '搜索已启用',
              disabled: '搜索未启用',
            })}
          </span>
        </div>
      )}
      styles={{ body: { padding: '10px 12px 8px' } }}
    >
      <div className="beacon-faces-workspace-toolbar">
        <div className="beacon-faces-workspace-toolbar__filters">
          <Input
            allowClear
            className="beacon-faces-workspace-toolbar__search"
            placeholder="搜索人脸名称 / ID / 标签"
            prefix={<SearchOutlined />}
            value={tableQuery}
            onChange={(event) => onTableQueryChange(event.target.value)}
          />
          <Select
            allowClear
            className="beacon-faces-workspace-toolbar__group"
            placeholder="分组"
            value={groupFilter || undefined}
            options={groupOptions}
            onChange={(value) => onGroupFilterChange(value || '')}
          />
          <Button
            icon={<SettingOutlined />}
            onClick={onResetFilters}
            disabled={!tableQuery && !groupFilter}
          >
            重置
          </Button>
        </div>
        <Text type="secondary" className="beacon-faces-workspace-toolbar__hint">
          优先展示直连人脸库数据；直连失败时自动切换到兼容回退结果。
        </Text>
      </div>

      <ProTable
        rowKey="_rowKey"
        columns={columns}
        dataSource={pagedRows}
        loading={showInlineLoading}
        pagination={false}
        scroll={{ x: 1160 }}
      />
      <div className="beacon-faces-pagination-bar">
        <span className="beacon-faces-pagination-bar__summary">
          第 {currentPage} / {totalPages} 页，共 {filteredRows.length} 条
        </span>
        <Pagination
          current={currentPage}
          pageSize={tablePagination.pageSize}
          total={filteredRows.length}
          size="small"
          showSizeChanger
          pageSizeOptions={['10', '20', '50', '100']}
          onChange={onPaginationChange}
        />
      </div>
    </Card>
  );
}

function FaceAddModal({ open, form, submitting, onClose, onSubmit }) {
  return (
    <Modal
      title="新增人脸"
      open={open}
      onCancel={onClose}
      onOk={onSubmit}
      okText="提交"
      confirmLoading={submitting}
      destroyOnHidden
    >
      <Form form={form} layout="vertical">
        <Form.Item name="id" label="ID" rules={[{ required: true, message: '请输入 ID' }]}>
          <Input autoComplete="off" />
        </Form.Item>
        <Form.Item name="name" label="名称">
          <Input autoComplete="off" />
        </Form.Item>
        <Form.Item name="embedding_json" label="Embedding JSON">
          <Input.TextArea rows={4} placeholder='例如: [1, 0, 0.1]' />
        </Form.Item>
        <Form.Item name="image_base64" label="Image Base64">
          <Input.TextArea rows={3} placeholder="可选，传图片时后端会按配置补齐特征算法" />
        </Form.Item>
        <Form.Item name="featureAlgorithmCode" label="特征算法编码">
          <Input placeholder="可选，例如 on_xcfacenet_default" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function FaceSearchModal({ open, form, result, submitting, onClose, onSubmit }) {
  return (
    <Modal
      title="相似搜索"
      open={open}
      onCancel={onClose}
      onOk={onSubmit}
      okText="搜索"
      confirmLoading={submitting}
      destroyOnHidden
    >
      <Form form={form} layout="vertical">
        <Form.Item name="embedding_json" label="Embedding JSON">
          <Input.TextArea rows={4} placeholder='例如: [1, 0, 0.1]' />
        </Form.Item>
        <Form.Item name="image_base64" label="Image Base64">
          <Input.TextArea rows={3} />
        </Form.Item>
        <Form.Item name="featureAlgorithmCode" label="特征算法编码">
          <Input />
        </Form.Item>
        <Form.Item name="minScore" label="最小分数">
          <Input placeholder="可选，例如 0.8" />
        </Form.Item>
      </Form>

      {result ? <FaceSearchResult result={result} /> : null}
    </Modal>
  );
}

function FaceSearchResult({ result }) {
  return (
    <Card className="beacon-panel-card beacon-panel-card--tone-cyan" size="small" style={{ marginTop: 12 }}>
      <Descriptions
        bordered
        size="small"
        column={1}
        items={[
          { key: 'found', label: '命中', children: result.found ? '是' : '否' },
          { key: 'score', label: '分数', children: result.score == null ? '-' : String(result.score) },
          { key: 'face', label: '结果', children: result.item ? JSON.stringify(result.item) : '-' },
        ]}
      />
    </Card>
  );
}

function FaceErrorDetailModal({ open, errorSummaryItems, rawDetail, onClose }) {
  return (
    <Modal
      title="错误详情"
      open={open}
      footer={null}
      onCancel={onClose}
      destroyOnHidden
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Descriptions
          bordered
          size="small"
          column={1}
          items={errorSummaryItems.map((item) => ({
            key: item.key,
            label: item.label,
            children: item.value,
          }))}
        />
        <pre className="beacon-json-card__pre beacon-faces-error-pre">
          {rawDetail || '当前没有原始错误详情。'}
        </pre>
      </Space>
    </Modal>
  );
}

FacesHeader.propTypes = {
  searchEnabled: PropTypes.bool,
  directLoading: PropTypes.bool,
  onReload: PropTypes.func,
  onToggle: PropTypes.func,
  onAdd: PropTypes.func,
  onSearch: PropTypes.func,
};

FacesIssueAlert.propTypes = {
  errorInsight: PropTypes.object,
  fallbackRowsCount: PropTypes.number,
  onOpenDetail: PropTypes.func,
};

FacesOverviewCard.propTypes = {
  overviewMetrics: PropTypes.array,
  overviewFacts: PropTypes.array,
  directError: PropTypes.object,
};

FacesErrorCard.propTypes = {
  errorInsight: PropTypes.object,
  errorSummaryItems: PropTypes.array,
  fallbackRowsCount: PropTypes.number,
  onOpenDetail: PropTypes.func,
};

FacesTopGrid.propTypes = {
  overviewMetrics: PropTypes.array,
  overviewFacts: PropTypes.array,
  directError: PropTypes.object,
  errorInsight: PropTypes.object,
  errorSummaryItems: PropTypes.array,
  fallbackRowsCount: PropTypes.number,
  onOpenDetail: PropTypes.func,
};

FacesWorkspaceCard.propTypes = {
  filteredRows: PropTypes.array,
  rows: PropTypes.array,
  searchEnabled: PropTypes.bool,
  tableQuery: PropTypes.string,
  groupFilter: PropTypes.string,
  groupOptions: PropTypes.array,
  columns: PropTypes.array,
  pagedRows: PropTypes.array,
  showInlineLoading: PropTypes.bool,
  currentPage: PropTypes.number,
  totalPages: PropTypes.number,
  tablePagination: PropTypes.object,
  onTableQueryChange: PropTypes.func,
  onGroupFilterChange: PropTypes.func,
  onResetFilters: PropTypes.func,
  onPaginationChange: PropTypes.func,
};

FaceAddModal.propTypes = {
  open: PropTypes.bool,
  form: PropTypes.object,
  submitting: PropTypes.bool,
  onClose: PropTypes.func,
  onSubmit: PropTypes.func,
};

FaceSearchModal.propTypes = {
  open: PropTypes.bool,
  form: PropTypes.object,
  result: PropTypes.object,
  submitting: PropTypes.bool,
  onClose: PropTypes.func,
  onSubmit: PropTypes.func,
};

FaceSearchResult.propTypes = {
  result: PropTypes.object,
};

FaceErrorDetailModal.propTypes = {
  open: PropTypes.bool,
  errorSummaryItems: PropTypes.array,
  rawDetail: PropTypes.string,
  onClose: PropTypes.func,
};

export default function FacesPage() {
  const { message } = App.useApp();
  const { data, loading, error, run } = useApi(API.faces);
  const [directRows, setDirectRows] = useState([]);
  const [directMeta, setDirectMeta] = useState({ count: 0, dim: '-', searchEnabled: null });
  const [directLoading, setDirectLoading] = useState(true);
  const [directError, setDirectError] = useState(null);
  const [addOpen, setAddOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchResult, setSearchResult] = useState(null);
  const [errorDetailOpen, setErrorDetailOpen] = useState(false);
  const [tableQuery, setTableQuery] = useState('');
  const [groupFilter, setGroupFilter] = useState('');
  const [tablePagination, setTablePagination] = useState({ current: 1, pageSize: 20 });
  const [submitting, setSubmitting] = useState(false);
  const [addForm] = Form.useForm();
  const [searchForm] = Form.useForm();

  const refreshDirectList = useCallback(async () => {
    setDirectLoading(true);
    setDirectError(null);
    try {
      const payload = await apiPost(API.faceList, {});
      const items = Array.isArray(payload?.items) ? payload.items : [];
      setDirectRows(items.map((row, index) => ({ ...row, _rowKey: row.id ?? row.face_id ?? index })));
      setDirectMeta({
        count: Number(payload?.count ?? items.length ?? 0),
        dim: payload?.dim ?? '-',
        searchEnabled: payload?.searchEnabled ?? null,
      });
    } catch (e) {
      setDirectError(e);
      setDirectRows([]);
      setDirectMeta({ count: 0, dim: '-', searchEnabled: null });
    } finally {
      setDirectLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshDirectList();
  }, [refreshDirectList]);

  const fallbackRows = useMemo(() => normalizeFallbackRows(data?.face_db), [data?.face_db]);
  const rows = useMemo(() => (directRows.length || !directError ? directRows : fallbackRows), [directError, directRows, fallbackRows]);
  const searchEnabled = directMeta.searchEnabled;

  const reloadAll = useCallback(() => {
    run();
    refreshDirectList();
  }, [refreshDirectList, run]);

  const postFaceAction = useCallback(
    async (url, body, okMessage) => {
      setSubmitting(true);
      try {
        const result = await apiPost(url, body);
        message.success(okMessage);
        await refreshDirectList();
        return result;
      } catch (e) {
        message.error(e?.message || '操作失败');
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [message, refreshDirectList],
  );

  const handleToggle = useCallback(async () => {
    const enable = !searchEnabled;
    const result = await postFaceAction(enable ? API.faceEnable : API.faceDisable, {}, enable ? '已启用人脸搜索' : '已停用人脸搜索');
    if (result) {
      setDirectMeta((prev) => ({ ...prev, searchEnabled: enable }));
    }
  }, [postFaceAction, searchEnabled]);

  const handleAdd = useCallback(async () => {
    try {
      const values = await addForm.validateFields();
      const body = {
        id: String(values.id || '').trim(),
        name: String(values.name || '').trim(),
        ...buildFaceActionBody(values),
      };
      if (!hasFaceVectorSource(body)) {
        message.error('请提供 Embedding JSON 或 Image Base64');
        return;
      }
      const result = await postFaceAction(API.faceAdd, body, '人脸已提交');
      if (result) {
        addForm.resetFields();
        setAddOpen(false);
      }
    } catch (e) {
      if (!e?.errorFields) {
        message.error(e?.message || '提交失败');
      }
    }
  }, [addForm, message, postFaceAction]);

  const handleSearch = useCallback(async () => {
    try {
      const values = await searchForm.validateFields();
      const body = buildFaceActionBody(values, { includeMinScore: true });
      if (!hasFaceVectorSource(body)) {
        message.error('请提供 Embedding JSON 或 Image Base64');
        return;
      }
      setSubmitting(true);
      try {
        const result = await apiPost(API.faceSearch, body);
        setSearchResult(result || null);
        message.success('搜索完成');
      } finally {
        setSubmitting(false);
      }
    } catch (e) {
      if (!e?.errorFields) {
        message.error(e?.message || '搜索失败');
      }
    }
  }, [message, searchForm]);

  const handleDelete = useCallback(
    async (faceId) => {
      const result = await postFaceAction(API.faceDelete, { id: faceId }, '已删除人脸');
      if (!result) return;
      setSearchResult((prev) => {
        if (!prev?.item) return prev;
        return prev.item.id === faceId ? null : prev;
      });
    },
    [postFaceAction],
  );

  const hasBootstrappedContent = Boolean(data) || rows.length > 0;
  const showBlockingSpinner = (loading || directLoading) && !hasBootstrappedContent;
  const showInlineLoading = (loading || directLoading) && hasBootstrappedContent;

  const groupOptions = useMemo(() => buildFaceGroupOptions(rows), [rows]);

  const filteredRows = useMemo(() => filterFaceRows(rows, { tableQuery, groupFilter }), [groupFilter, rows, tableQuery]);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(filteredRows.length / tablePagination.pageSize)),
    [filteredRows.length, tablePagination.pageSize],
  );
  const currentPage = Math.min(tablePagination.current, totalPages);
  const pagedRows = useMemo(() => {
    const start = (currentPage - 1) * tablePagination.pageSize;
    return filteredRows.slice(start, start + tablePagination.pageSize);
  }, [currentPage, filteredRows, tablePagination.pageSize]);

  const overviewMetrics = useMemo(
    () => buildFaceOverviewMetrics({ rows, directError, directMeta, groupOptions }),
    [directError, directMeta, groupOptions, rows],
  );

  const overviewFacts = useMemo(
    () => buildFaceOverviewFacts({ data, directError, fallbackRows, searchEnabled }),
    [data, directError, fallbackRows, searchEnabled],
  );

  const errorInsight = useMemo(
    () => buildFaceErrorInsight({
      error,
      directError,
      fallbackError: data?.face_db_error,
      fallbackRowsCount: fallbackRows.length,
    }),
    [data?.face_db_error, directError, error, fallbackRows.length],
  );

  const errorSummaryItems = useMemo(
    () => [
      { key: 'source', label: '异常来源', value: errorInsight.sourceLabel },
      { key: 'host', label: '目标地址', value: errorInsight.hostPort },
      { key: 'endpoint', label: '请求路径', value: errorInsight.endpoint },
      { key: 'fallback', label: '页面回退', value: errorInsight.fallbackState },
    ],
    [errorInsight.endpoint, errorInsight.fallbackState, errorInsight.hostPort, errorInsight.sourceLabel],
  );

  const resetFilters = useCallback(() => {
    setTableQuery('');
    setGroupFilter('');
    setTablePagination((prev) => ({ ...prev, current: 1 }));
  }, []);

  const updateTableQuery = useCallback((value) => {
    setTableQuery(value);
    setTablePagination((prev) => ({ ...prev, current: 1 }));
  }, []);

  const updateGroupFilter = useCallback((value) => {
    setGroupFilter(value);
    setTablePagination((prev) => ({ ...prev, current: 1 }));
  }, []);

  const handlePaginationChange = useCallback((page, pageSize) => {
    setTablePagination((prev) => ({
      current: page || 1,
      pageSize: pageSize || prev.pageSize,
    }));
  }, []);

  useEffect(() => {
    if (tablePagination.current > totalPages) {
      setTablePagination((prev) => ({ ...prev, current: totalPages }));
    }
  }, [tablePagination.current, totalPages]);

  const columns = useMemo(() => buildFaceColumns(handleDelete), [handleDelete]);

  return (
    <div className="beacon-faces-page beacon-faces-page--compact">
      <FacesHeader
        searchEnabled={searchEnabled}
        directLoading={directLoading}
        onReload={reloadAll}
        onToggle={handleToggle}
        onAdd={() => setAddOpen(true)}
        onSearch={() => setSearchOpen(true)}
      />
      <FacesIssueAlert
        errorInsight={errorInsight}
        fallbackRowsCount={fallbackRows.length}
        onOpenDetail={() => setErrorDetailOpen(true)}
      />

      <Spin spinning={showBlockingSpinner}>
        <div className="beacon-faces-support-grid">
          <FacesTopGrid
            overviewMetrics={overviewMetrics}
            overviewFacts={overviewFacts}
            directError={directError}
            errorInsight={errorInsight}
            errorSummaryItems={errorSummaryItems}
            fallbackRowsCount={fallbackRows.length}
            onOpenDetail={() => setErrorDetailOpen(true)}
          />
          <FacesWorkspaceCard
            filteredRows={filteredRows}
            rows={rows}
            searchEnabled={searchEnabled}
            tableQuery={tableQuery}
            groupFilter={groupFilter}
            groupOptions={groupOptions}
            columns={columns}
            pagedRows={pagedRows}
            showInlineLoading={showInlineLoading}
            currentPage={currentPage}
            totalPages={totalPages}
            tablePagination={tablePagination}
            onTableQueryChange={updateTableQuery}
            onGroupFilterChange={updateGroupFilter}
            onResetFilters={resetFilters}
            onPaginationChange={handlePaginationChange}
          />
        </div>
      </Spin>

      <FaceAddModal
        open={addOpen}
        form={addForm}
        submitting={submitting}
        onClose={() => setAddOpen(false)}
        onSubmit={handleAdd}
      />
      <FaceSearchModal
        open={searchOpen}
        form={searchForm}
        result={searchResult}
        submitting={submitting}
        onClose={() => setSearchOpen(false)}
        onSubmit={handleSearch}
      />
      <FaceErrorDetailModal
        open={errorDetailOpen}
        errorSummaryItems={errorSummaryItems}
        rawDetail={errorInsight.rawDetail}
        onClose={() => setErrorDetailOpen(false)}
      />
    </div>
  );
}
