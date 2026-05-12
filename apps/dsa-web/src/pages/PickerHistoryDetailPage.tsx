import type React from 'react';
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Spinner } from '../components/common';
import { fetchPickerDetail, type PickerResponse } from '../api/picker';
import { ResultView } from './picker/components/ResultView';

const PickerHistoryDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const numId = Number(id);
  const idValid = !!id && Number.isFinite(numId);
  const [loading, setLoading] = useState(idValid);
  const [result, setResult] = useState<PickerResponse | null>(null);
  const [error, setError] = useState(idValid ? '' : '历史记录 ID 无效');

  useEffect(() => {
    if (!idValid) return;
    let cancelled = false;
    const load = async () => {
      try {
        const data = await fetchPickerDetail(numId);
        if (cancelled) return;
        if (!data || (data as PickerResponse).success === false) {
          setError((data as PickerResponse)?.error || '历史记录数据不完整');
        } else {
          const picks = (data as PickerResponse).picks;
          if (!picks || picks.length === 0) {
            setError('该历史记录无推荐数据');
          } else {
            setResult(data as PickerResponse);
          }
        }
      } catch {
        if (!cancelled) setError('加载历史记录失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => { cancelled = true; };
  }, [idValid, numId]);

  const onBack = () => navigate('/picker');

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-6xl mx-auto px-6 py-6">
        {loading && (
          <div className="flex flex-col items-center py-20">
            <Spinner size="lg" />
            <p className="mt-6 text-base text-primary font-semibold">加载历史记录...</p>
          </div>
        )}

        {error && !loading && (
          <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-center">
            <p className="text-base text-red-700 font-medium">{error}</p>
            <button
              onClick={onBack}
              className="mt-3 text-sm text-red-600 underline hover:no-underline font-medium"
            >
              返回选股列表
            </button>
          </div>
        )}

        {result && !loading && !error && (
          <ResultView result={result} onBack={onBack} />
        )}
      </div>
    </div>
  );
};

export default PickerHistoryDetailPage;
