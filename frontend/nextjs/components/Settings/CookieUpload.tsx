import React, {useState, useEffect} from 'react';
import axios from 'axios';
import {getHost} from '@/helpers/getHost';

const CookieUpload = () => {
  const [status, setStatus] = useState<{exists: boolean; size: number} | null>(null);
  const [uploading, setUploading] = useState(false);
  const [msg, setMsg] = useState('');
  const host = getHost();

  const fetchStatus = async () => {
    try {
      const res = await axios.get(host + '/api/cookies/status');
      setStatus(res.data);
    } catch (e: any) {
      console.error('Cookie status fetch failed:', e);
    }
  };

  useEffect(() => { fetchStatus(); }, []);

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    setUploading(true);
    setMsg('');
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await axios.post(host + '/api/cookies/upload', form);
      setMsg(res.data.message + ' (' + res.data.size + ' bytes)');
      fetchStatus();
    } catch (err: any) {
      setMsg('Upload failed: ' + (err.response && err.response.data ? err.response.data.detail : err.message));
    }
    setUploading(false);
    e.target.value = '';
  };

  return React.createElement('div', {className: 'w-full mb-6 p-4 rounded-lg bg-gray-800/40 border border-gray-700/50'},
    React.createElement('h3', {className: 'text-lg font-semibold text-teal-400 mb-2'}, 'Video Platform Cookie'),
    React.createElement('p', {className: 'text-sm text-gray-400 mb-3'},
      'Douyin/Bilibili comments require login cookies. Export cookies using browser extension.'
    ),
    React.createElement('div', {className: 'flex items-center gap-3'},
      React.createElement('label', {className: 'cursor-pointer px-4 py-2 bg-teal-600 hover:bg-teal-500 text-white text-sm rounded-md'},
        uploading ? 'Uploading...' : 'Upload cookies.txt',
        React.createElement('input', {type: 'file', accept: '.txt', onChange: onUpload, className: 'hidden', disabled: uploading})
      ),
      status && React.createElement('span', {className: status.exists ? 'text-green-400 text-xs' : 'text-yellow-400 text-xs'},
        status.exists ? 'OK - ' + status.size + ' bytes' : 'No cookie file'
      )
    ),
    msg && React.createElement('p', {className: 'mt-2 text-sm text-gray-300'}, msg)
  );
};

export default CookieUpload;
