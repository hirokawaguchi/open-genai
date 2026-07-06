import { useEffect, useRef, useState } from 'react';
import { PiLightbulbFilamentBold, PiWarningFill } from 'react-icons/pi';
import { Button } from '@/components/ui/dads/Button';
import { ProgressIndicator } from '@/components/ui/dads/ProgressIndicator';
import { Ul } from '@/components/ui/dads/Ul';
import { useGenerateImageStore } from '@/features/generate-image/stores/useGenerateImageStore';
import { useChat } from '@/hooks/useChat';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { useFollow } from '@/hooks/useFollow';
import { useLiveStatusMessage } from '@/hooks/useLiveStatusMessage';
import { useScreen } from '@/hooks/useScreen';

type Props = {
  isGeneratingImage: boolean;
  onGenerate: (prompt: string, negativePrompt: string, stylePreset?: string) => Promise<void>;
};

type AssistantImageContent = {
  prompt: string | null;
  negativePrompt: string | null;
  comment: string;
  recommendedStylePreset: string[];
  error?: boolean;
};

const parseAssistantImageContent = (content: string): AssistantImageContent => {
  const fenced = content.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const candidate = (fenced ? fenced[1] : content).trim();
  const start = candidate.indexOf('{');
  const end = candidate.lastIndexOf('}');
  if (start < 0 || end <= start) {
    throw new Error('JSON not found');
  }
  const parsed = JSON.parse(candidate.slice(start, end + 1)) as Partial<AssistantImageContent>;
  return {
    prompt: parsed.prompt ?? null,
    negativePrompt: parsed.negativePrompt ?? null,
    comment: parsed.comment ?? '',
    recommendedStylePreset: parsed.recommendedStylePreset ?? [],
  };
};

export const GenerateImageAssistant = (props: Props) => {
  const { isGeneratingImage, onGenerate } = props;
  const { usecase, chatId } = useUsecasePath();
  const { stylePreset } = useGenerateImageStore();
  const { loading, messages, postChat, popMessage } = useChat(usecase, chatId);
  const [isAutoGenerating, setIsAutoGenerating] = useState(false);
  const [isPresetGenerating, setIsPresetGenerating] = useState(false);
  const wasPromptLoadingRef = useRef(false);
  const { scrollTopAnchorRef, scrollBottomAnchorRef } = useScreen({ useWindowScroll: true });
  const { scrollableContainer, setFollowing } = useFollow();

  useEffect(() => {
    if (loading) {
      setFollowing(true);
    }
  }, [loading, setFollowing]);

  const contents: (
    | {
        role: 'user';
        content: string;
      }
    | {
        role: 'assistant';
        content: {
          prompt: string | null;
          negativePrompt: string | null;
          comment: string;
          recommendedStylePreset: string[];
          error?: boolean;
        };
      }
  )[] = messages.flatMap((m, idx) => {
    if (m.role === 'user') {
      return {
        role: 'user',
        content: m.content,
      };
    } else {
      if (loading && messages.length - 1 === idx) {
        return {
          role: 'assistant',
          content: {
            prompt: null,
            negativePrompt: null,
            comment: '',
            recommendedStylePreset: [],
          },
        };
      }
      try {
        return {
          role: 'assistant',
          content: parseAssistantImageContent(m.content),
        };
      } catch (e) {
        console.error(e);
        return {
          role: 'assistant',
          content: {
            prompt: null,
            negativePrompt: null,
            comment: '',
            error: true,
            recommendedStylePreset: [],
          },
        };
      }
    }
  });

  useEffect(() => {
    // プロンプト生成（postChat のストリーム）が完了した直後のみ画像を自動生成する。
    // 履歴復元時は loading が true にならないため、再生成を防げる。
    if (loading) {
      wasPromptLoadingRef.current = true;
      return;
    }

    if (!wasPromptLoadingRef.current || contents.length === 0) {
      return;
    }
    wasPromptLoadingRef.current = false;

    const idx = contents.length - 1;
    const message = contents[idx];
    if (
      message.role === 'assistant' &&
      message.content.prompt &&
      message.content.negativePrompt !== null &&
      !message.content.error
    ) {
      setIsAutoGenerating(true);
      onGenerate(message.content.prompt, message.content.negativePrompt ?? '').finally(() => {
        setIsAutoGenerating(false);
      });
    }
  }, [loading, contents, onGenerate]);

  const onRetrySend = () => {
    popMessage();
    const lastMessage = popMessage();
    postChat(lastMessage?.content ?? '');
  };

  const lastMessage = contents.length > 0 ? contents[contents.length - 1] : null;
  const assistantContent = lastMessage?.role === 'assistant' ? lastMessage?.content.comment : '';
  const { liveStatusMessage } = useLiveStatusMessage({
    active: lastMessage?.role === 'assistant',
    loading: loading || isAutoGenerating,
    messages: {
      loading: 'AIが回答を生成しています...',
      loadingContinue: 'AIが引き続き回答を生成しています...',
      completed: assistantContent ? `AIの回答：${assistantContent}` : 'AIの回答がありません。',
    },
  });
  const { liveStatusMessage: presetStatusMessage } = useLiveStatusMessage({
    active: true,
    loading: isPresetGenerating,
    messages: {
      loading: 'AIが画像を生成しています...',
      loadingContinue: 'AIが引き続き画像を生成しています...',
      completed: '画像の生成が完了しました',
    },
  });

  return (
    <>
      <div ref={scrollTopAnchorRef} />
      {contents.length === 0 ? (
        <div>
          <p className='mb-3'>チャット形式でプロンプトの生成と設定、画像生成を自動で行います。</p>
          <p className='mb-6'>
            ※生成された画像の利用にあたっては、各ユーザーによってその利用が適切かどうかご判断ください。
          </p>
          <div className='rounded-16 border border-solid-gray-536 bg-solid-gray-50 px-8 py-6 text-solid-gray-800 xl:px-10 xl:py-6'>
            <h2 className='mb-6 flex items-center text-std-18B-160'>
              <PiLightbulbFilamentBold className='mr-2 size-6' />
              ヒント
            </h2>
            <Ul className='pl-6! space-y-1'>
              <li>
                具体的かつ詳細な指示を出すようにしましょう。
                形容詞や副詞を使って、正確に表現することが重要です。
              </li>
              <li>
                「犬が遊んでいる」ではなく、「柴犬が草原で楽しそうに走り回っている」のように具体的に指示をしましょう。
              </li>
              <li>
                文章で書くことが難しい場合は、文章で書く必要はありません。「元気、ボール遊び、ジャンプしている」のように、特徴を羅列して指示をしましょう。
              </li>
              <li>除外して欲しい要素も指示することができます。「人間は出力しない」など。</li>
              <li>
                AIが会話の流れを考慮してくれるので、「やっぱり犬じゃなくて猫にして」などの会話形式の指示もできます。
              </li>
              <li>
                プロンプトで意図した画像が生成できない場合は、初期画像の設定やパラメータの変更を試してみましょう。
              </li>
            </Ul>
          </div>
        </div>
      ) : (
        <div className='mt-4 flex flex-col gap-4' ref={scrollableContainer}>
          {contents.map((c, idx) =>
            c.role === 'user' ? (
              <article key={idx} className='bg-solid-gray-50 p-4 rounded-12 lg:p-6'>
                <h2 className='sr-only'>あなたの質問</h2>
                <div className='whitespace-pre-wrap'>{c.content}</div>
              </article>
            ) : (
              <article
                key={idx}
                className='border border-solid-gray-420 bg-white p-4 rounded-12 lg:p-6'
              >
                <h2 className='sr-only'>AIの回答</h2>
                {c.content.error && (
                  <div>
                    <div className='flex items-center gap-2 font-700 text-error-1'>
                      <PiWarningFill aria-hidden={true} />
                      エラー
                    </div>
                    <p>プロンプト生成中にエラーが発生しました。</p>
                    <div className='mt-3 flex w-full'>
                      <Button variant='outline' size='sm' onClick={onRetrySend}>
                        再実行
                      </Button>
                    </div>
                  </div>
                )}
                {c.content.prompt === null && !c.content.error && (
                  <div className='flex items-center gap-2'>
                    <ProgressIndicator label='プロンプト生成中' />
                  </div>
                )}
                {c.content.prompt !== null &&
                  (contents.length - 1 === idx && isGeneratingImage && isAutoGenerating ? (
                    <>
                      <div className='flex items-center gap-1'>
                        <div className='mr-1.5 ml-0.5 size-5 rounded-full border-3 border-success-1' />
                        プロンプト生成完了
                      </div>
                      <div className='mt-2 flex items-center gap-1'>
                        <ProgressIndicator label='画像生成中' />
                      </div>
                    </>
                  ) : (
                    <>
                      {c.content.comment.split('\n').map((m, lineIdx) => (
                        <div key={lineIdx}>{m}</div>
                      ))}
                      <div className='mt-4 flex flex-col gap-1.5'>
                        <h3
                          id={`recommended-style-preset-heading-${idx}`}
                          className='text-std-18B-160'
                        >
                          おすすめのスタイルプリセット（{stylePreset || '未設定'}
                          {stylePreset && 'を選択中'}）
                        </h3>
                        <p id={`recommended-style-preset-support-${idx}`}>
                          選択するとすぐに画像が再生成されます
                        </p>
                        <div className='mt-3 grid grid-cols-2 gap-1 xl:flex xl:gap-3'>
                          {c.content.recommendedStylePreset.flatMap((preset, presetIdx) => (
                            <Button
                              variant='outline'
                              size='sm'
                              key={presetIdx}
                              id={`recommended-style-preset-${idx}-${presetIdx}`}
                              aria-labelledby={`recommended-style-preset-heading-${idx} recommended-style-preset-${idx}-${presetIdx}`}
                              aria-describedby={`recommended-style-preset-support-${idx}`}
                              onClick={() => {
                                if (preset === stylePreset) return;
                                setIsPresetGenerating(true);
                                onGenerate(
                                    c.content.prompt ?? '',
                                    c.content.negativePrompt ?? '',
                                    preset,
                                  )
                                  .finally(() => setIsPresetGenerating(false));
                              }}
                            >
                              {preset}
                            </Button>
                          ))}
                          <Button
                            variant='text'
                            size='sm'
                            id={`recommended-style-preset-${idx}-reset`}
                            aria-labelledby={`recommended-style-preset-heading-${idx} recommended-style-preset-${idx}-reset`}
                            aria-describedby={`recommended-style-preset-support-${idx}`}
                            onClick={() => {
                              if (stylePreset === '') return;
                              setIsPresetGenerating(true);
                              onGenerate(
                                c.content.prompt ?? '',
                                c.content.negativePrompt ?? '',
                                '',
                              ).finally(() => setIsPresetGenerating(false));
                            }}
                          >
                            未設定
                          </Button>
                        </div>
                      </div>
                    </>
                  ))}
              </article>
            ),
          )}
        </div>
      )}
      <div ref={scrollBottomAnchorRef} />
      <div aria-live='assertive' aria-atomic='true' className='sr-only'>
        {liveStatusMessage}
      </div>
      <div aria-live='assertive' aria-atomic='true' className='sr-only'>
        {presetStatusMessage}
      </div>
    </>
  );
};
