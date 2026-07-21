import React from 'react';
import { getBootstrapQuery } from '../../bootstrap';
import AlarmDetailDrawer from './AlarmDetailDrawer';

export default function AlarmDetailPage() {
  const query = getBootstrapQuery();
  const alarmId = query.get('id');

  return (
    <AlarmDetailDrawer
      open={true}
      alarmId={alarmId}
      onAction={() => {}}
    />
  );
}
