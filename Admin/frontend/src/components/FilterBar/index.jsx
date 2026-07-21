import React, { useEffect, useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import { Space, Input, Select, Button, DatePicker } from 'antd';
import { SearchOutlined, ReloadOutlined, DownOutlined, UpOutlined } from '@ant-design/icons';
import './FilterBar.css';

const { RangePicker } = DatePicker;

export default function FilterBar({ filters = [], onSearch, onReset, extra, expandThreshold = 3, initialValues = {} }) {
  const [expanded, setExpanded] = useState(false);
  const initialValuesKey = useMemo(() => JSON.stringify(initialValues || {}), [initialValues]);
  const [values, setValues] = useState(initialValues || {});

  useEffect(() => {
    setValues(initialValues || {});
  }, [initialValuesKey]);

  const visibleFilters = expanded ? filters : filters.slice(0, expandThreshold);
  const hasMore = filters.length > expandThreshold;

  const handleChange = (key, val) => {
    setValues(prev => ({ ...prev, [key]: val }));
  };

  const handleSearch = () => {
    onSearch?.(values);
  };

  const handleReset = () => {
    setValues({});
    onReset?.();
  };

  const renderFilter = (f) => {
    switch (f.type) {
      case 'select':
        return (
          <Select
            key={f.key}
            placeholder={f.placeholder || f.label}
            value={values[f.key]}
            onChange={v => handleChange(f.key, v)}
            options={f.options || []}
            allowClear
            style={{ minWidth: 140 }}
            size="middle"
          />
        );
      case 'dateRange':
        return (
          <RangePicker
            key={f.key}
            value={values[f.key]}
            onChange={v => handleChange(f.key, v)}
            size="middle"
          />
        );
      default:
        return (
          <Input
            key={f.key}
            placeholder={f.placeholder || f.label}
            value={values[f.key]}
            onChange={e => handleChange(f.key, e.target.value)}
            allowClear
            style={{ width: 180 }}
            size="middle"
            prefix={<SearchOutlined />}
          />
        );
    }
  };

  return (
    <div className="beacon-filter-bar">
      <Space wrap size={[8, 8]}>
        {visibleFilters.map(renderFilter)}
        <Button
          type="primary"
          className="beacon-filter-bar__search-btn"
          icon={<SearchOutlined />}
          onClick={handleSearch}
          size="middle"
        >
          搜索
        </Button>
        <Button icon={<ReloadOutlined />} onClick={handleReset} size="middle">重置</Button>
        {hasMore && (
          <Button type="link" size="small" onClick={() => setExpanded(!expanded)}>
            {expanded ? <>收起 <UpOutlined /></> : <>展开 <DownOutlined /></>}
          </Button>
        )}
        {extra}
      </Space>
    </div>
  );
}

FilterBar.propTypes = {
  filters: PropTypes.arrayOf(PropTypes.shape({
    key: PropTypes.string.isRequired,
    type: PropTypes.string,
    label: PropTypes.node,
    placeholder: PropTypes.string,
    options: PropTypes.array,
  })),
  onSearch: PropTypes.func,
  onReset: PropTypes.func,
  extra: PropTypes.node,
  expandThreshold: PropTypes.number,
  initialValues: PropTypes.object,
};
