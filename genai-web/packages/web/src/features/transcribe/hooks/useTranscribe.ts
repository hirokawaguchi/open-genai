import { fileObjectKeyFromUrl } from '@/lib/fileUrl';
import { useTranscribeStore } from '../stores/useTranscribeStore';
import { useFetchTranscription } from './useFetchTranscription';
import { useTranscribeApi } from './useTranscribeApi';

export const useTranscribe = () => {
  const api = useTranscribeApi();
  const { file, loading, setLoading, setFile, setJobName, clear } = useTranscribeStore();
  const { transcriptData } = useFetchTranscription();

  const transcribe = async (targetFile: File, speakerLabel = false, maxSpeakers = 1) => {
    setJobName(null);
    setLoading(true);
    setFile(targetFile);

    const mediaFormat = targetFile.name.split('.').pop();
    if (!mediaFormat) {
      return;
    }

    // 署名付き URL の取得
    const signedUrlRes = await api.getSignedUrl({
      mediaFormat: mediaFormat,
    });
    const signedUrl = signedUrlRes.data;

    // 音声のアップロード
    await api.uploadAudio(signedUrl, { file: targetFile });

    // 署名付き URL からオブジェクトキーを抽出（/api プレフィックスは含めない）
    const audioKey = fileObjectKeyFromUrl(signedUrl);
    if (!audioKey) {
      setLoading(false);
      throw new Error('アップロード URL から音声キーを取得できませんでした');
    }

    // 音声認識
    const startTranscriptionRes = await api.startTranscription({
      audioKey: audioKey,
      speakerLabel: speakerLabel,
      maxSpeakers: maxSpeakers,
    });

    setJobName(startTranscriptionRes.jobName);
  };

  return {
    loading,
    transcriptData,
    file,
    setFile,
    transcribe,
    clear,
  };
};
