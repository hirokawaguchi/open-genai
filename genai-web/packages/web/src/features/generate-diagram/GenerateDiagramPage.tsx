import { PageTitle } from '@/components/PageTitle';
import { Divider } from '@/components/ui/dads/Divider';
import { APP_TITLE } from '@/constants';
import { DiagramGenerateForm } from '@/features/generate-diagram/components/DiagramGenerateForm';
import { DiagramGeneratingStep } from '@/features/generate-diagram/components/DiagramGeneratingStep';
import { DiagramHeader } from '@/features/generate-diagram/components/DiagramHeader';
import { DiagramResult } from '@/features/generate-diagram/components/DiagramResult';
import { DiagramSelectionStep } from '@/features/generate-diagram/components/DiagramSelectionStep';
import { DiagramSentence } from '@/features/generate-diagram/components/DiagramSentence';
import { useDiagram } from '@/features/generate-diagram/hooks/useDiagram';
import { useReset } from '@/features/generate-diagram/hooks/useReset';
import { useSetDefaultValues } from '@/features/generate-diagram/hooks/useSetDefaultValues';
import {
  extractDiagramCode,
  extractDiagramSentence,
} from '@/features/generate-diagram/utils/extractDiagram';
import { useLiveStatusMessage } from '@/hooks/useLiveStatusMessage';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { LayoutBody } from '@/layout/LayoutBody';

export const GenerateDiagramPage = () => {
  const { usecase, chatId } = useUsecasePath();
  const { loading, messages } = useDiagram(usecase, chatId);

  useReset();
  useSetDefaultValues();

  const lastMessage = messages.length > 0 ? messages[messages.length - 1] : null;
  const isAssistantMessage = lastMessage?.role === 'assistant';
  const assistantContent = isAssistantMessage ? lastMessage.content : '';
  const diagramCode = extractDiagramCode(assistantContent);
  const diagramSentence = isAssistantMessage ? extractDiagramSentence(assistantContent) : '';
  const diagramContent = lastMessage?.content ? diagramSentence : '';
  const { liveStatusMessage } = useLiveStatusMessage({
    active: isAssistantMessage,
    loading: loading,
    messages: {
      loading: 'AIが回答を生成しています...',
      loadingContinue: 'AIが引き続き回答を生成しています...',
      completed: diagramContent ? `AIの回答：${diagramContent}` : 'AIの回答がありません。',
    },
  });

  return (
    <LayoutBody>
      <PageTitle title={`ダイアグラムを生成${APP_TITLE ? ` | ${APP_TITLE}` : ''}`} />
      <div className='mx-auto p-6 max-w-(--page-width) lg:p-8'>
        <DiagramHeader />
        <Divider className='my-6' />
        <DiagramGenerateForm />
        <Divider className='my-3 lg:my-6' />
        <div className='w-full'>
          <h2 className='sr-only'>生成結果</h2>
          <div className='relative mt-5 min-h-20 rounded-8 border border-solid-gray-420 p-4'>
            <div className=''>
              {loading && (
                <div className='mb-4 space-y-2'>
                  <DiagramSelectionStep />

                  <DiagramGeneratingStep />
                </div>
              )}

              <div className='space-y-4'>
                <DiagramSentence diagramSentence={diagramSentence} />

                <DiagramResult diagramCode={diagramCode} />
              </div>
            </div>
          </div>
        </div>
      </div>
      <div aria-live='assertive' aria-atomic='true' className='sr-only'>
        {liveStatusMessage}
      </div>
    </LayoutBody>
  );
};
