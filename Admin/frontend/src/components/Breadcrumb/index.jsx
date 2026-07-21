import React from 'react';
import PropTypes from 'prop-types';
import { Breadcrumb as AntBreadcrumb } from 'antd';
import { HomeOutlined } from '@ant-design/icons';

/**
 * Route-to-label mapping for breadcrumb generation.
 * Keys are route paths; values are { label, parent? } descriptors.
 */
const ROUTE_LABELS = {
  '/': { label: '主页' },

  /* Alarms */
  '/alarms': { label: '报警管理' },
  '/alarm/detail': { label: '报警详情', parent: '/alarms' },
  '/alarm/review': { label: '报警审核', parent: '/alarms' },
  '/alarm_sound/index': { label: '报警声音' },

  /* Streams */
  '/stream/index': { label: '视频流' },
  '/stream/add': { label: '添加视频流', parent: '/stream/index' },
  '/stream/edit': { label: '编辑视频流', parent: '/stream/index' },
  '/stream/player': { label: '视频播放', parent: '/stream/index' },
  '/stream/multi': { label: '多路播放', parent: '/stream/index' },
  '/screen/index': { label: '大屏管理' },
  '/recording/manager': { label: '录像管理' },

  /* Controls */
  '/controls': { label: '布控列表' },
  '/control/add': { label: '添加布控', parent: '/controls' },
  '/control/edit': { label: '编辑布控', parent: '/controls' },
  '/control/logs': { label: '布控日志', parent: '/controls' },

  /* Algorithms */
  '/algorithm/index': { label: '算法列表' },
  '/algorithm/add': { label: '添加算法', parent: '/algorithm/index' },
  '/algorithm/edit': { label: '编辑算法', parent: '/algorithm/index' },
  '/algorithm/versions': { label: '算法版本', parent: '/algorithm/index' },

  /* Faces */
  '/face/index': { label: '人脸库' },

  /* Cloud */
  '/cloud/edge-clusters': { label: '云边连接' },
  '/cloud/alarms': { label: '云端告警' },
  '/cloud/alarm/detail': { label: '告警详情', parent: '/cloud/alarms' },
  '/cloud/remote/streams': { label: '远程流' },
  '/cloud/remote/stream/detail': { label: '流详情', parent: '/cloud/remote/streams' },
  '/cloud/remote/recordings': { label: '远程录像' },
  '/cloud/remote/platform': { label: '远程平台' },
  '/cloud/iam': { label: '权限管理' },

  /* Digital Human */
  '/digital-human/dashboard': { label: '数字人监管大盘' },
  '/digital-human/device-monitor': { label: '终端设备监控', parent: '/digital-human/dashboard' },
  '/digital-human/alert-center': { label: '告警中心', parent: '/digital-human/dashboard' },
  '/digital-human/monitor-logs': { label: '监管日志', parent: '/digital-human/dashboard' },
  '/digital-human/ops-report': { label: '运维报告', parent: '/digital-human/dashboard' },
  '/digital-human/system-settings': { label: '数字人系统设置', parent: '/digital-human/dashboard' },

  /* Ops */
  '/ops/diagnostics': { label: '诊断' },
  '/ops/platform': { label: '平台信息' },
  '/ops/upgrade': { label: '升级管理' },
  '/ops/audit': { label: '审计日志' },
  '/ops/apikeys': { label: 'API 密钥' },

  /* System */
  '/user/manage': { label: '用户管理' },
  '/config/system': { label: '系统设置' },
  '/config/export': { label: '导出配置' },
  '/config/import': { label: '导入配置' },
  '/config/history': { label: '配置历史' },
  '/license/manager': { label: '授权管理' },
  '/developer/index': { label: '开发者' },
  '/onvif/discover': { label: 'ONVIF 发现' },
  '/profile': { label: '个人信息' },
  '/login': { label: '登录' },
};

function buildCrumbs(path) {
  const crumbs = [];
  const entry = ROUTE_LABELS[path];

  if (!entry) {
    return [{ title: <HomeOutlined />, href: '/' }];
  }

  /* Walk up the parent chain */
  const chain = [];
  let current = path;
  const visited = new Set();
  while (current && ROUTE_LABELS[current] && !visited.has(current)) {
    visited.add(current);
    chain.unshift({ path: current, ...ROUTE_LABELS[current] });
    current = ROUTE_LABELS[current].parent;
  }

  /* Home is always first */
  crumbs.push({ title: <HomeOutlined />, href: '/' });

  chain.forEach((item, idx) => {
    const isLast = idx === chain.length - 1;
    if (isLast) {
      /* Last crumb is plain text */
      crumbs.push({ title: item.label });
    } else {
      crumbs.push({ title: <a href={item.path}>{item.label}</a> });
    }
  });

  return crumbs;
}

export default function BeaconBreadcrumb({ currentPath }) {
  if (!currentPath || currentPath === '/') return null;

  const items = buildCrumbs(currentPath);

  return (
    <div className="beacon-breadcrumb">
      <AntBreadcrumb items={items} />
    </div>
  );
}

BeaconBreadcrumb.propTypes = {
  currentPath: PropTypes.string,
};
