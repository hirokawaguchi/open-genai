import type { Placement } from '@floating-ui/react';
import {
  autoUpdate,
  flip,
  offset,
  safePolygon,
  shift,
  useDismiss,
  useFloating,
  useFocus,
  useHover,
  useInteractions,
  useMergeRefs,
} from '@floating-ui/react';
import * as React from 'react';

/**
 * NOTE:
 * 領域の制約でテキストラベルを入れることができないアイコンボタンなどにツールチップでラベルを表示する視覚的な補助のためのコンポーネントです。
 * [FLoatting UI](https://floating-ui.com/) を使用しており、以下のような構成で使用することを想定しています。
 *
 * 使用箇所に応じて `aria-hidden` や `aria-labelledby` を適切に設定してください。
 * 補足情報をツールチップで表示する場合は `role="tooltip"` と `aria-describedby` を付与してください。
 *
 * Example:
 *
 * ```tsx
 * <Tooltip>
 *   <TooltipTrigger asChild>
 *     <button
 *       type="button"
 *       onClick={...}>
 *       <CloseIcon aria-label="閉じる" role="img" />
 *     </button>
 *   </TooltipTrigger>
 *   <TooltipContent aria-hidden={true}>閉じる</TooltipContent>
 * </Tooltip>
 * ```
 */

interface TooltipOptions {
  initialOpen?: boolean;
  placement?: Placement;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  offset?: number; // 追加
  strategy?: 'absolute' | 'fixed';
}

const useTooltip = ({
  initialOpen = false,
  placement = 'top',
  open: controlledOpen,
  onOpenChange: setControlledOpen,
  offset: offsetValue = 4, // 追加: デフォルト4
  strategy = 'absolute',
}: TooltipOptions = {}) => {
  const [uncontrolledOpen, setUncontrolledOpen] = React.useState(initialOpen);

  const open = controlledOpen ?? uncontrolledOpen;
  const setOpen = setControlledOpen ?? setUncontrolledOpen;

  const data = useFloating({
    placement,
    strategy,
    open,
    onOpenChange: setOpen,
    whileElementsMounted: autoUpdate,
    middleware: [
      offset(offsetValue), // ここをpropsから
      flip({
        crossAxis: placement.includes('-'),
        fallbackAxisSideDirection: 'start',
        padding: 8,
      }),
      shift({ padding: 8 }),
    ],
  });

  const context = data.context;

  const hover = useHover(context, {
    move: false,
    enabled: controlledOpen == null,
    handleClose: safePolygon(),
  });
  const focus = useFocus(context, {
    enabled: controlledOpen == null,
  });
  const dismiss = useDismiss(context);

  const interactions = useInteractions([hover, focus, dismiss]);

  return React.useMemo(
    () => ({
      open,
      setOpen,
      ...interactions,
      ...data,
    }),
    [open, setOpen, interactions, data],
  );
};

type ContextType = ReturnType<typeof useTooltip> | null;

const TooltipContext = React.createContext<ContextType>(null);

const useTooltipContext = () => {
  const context = React.useContext(TooltipContext);

  if (context == null) {
    throw new Error('Tooltip components must be wrapped in <Tooltip />');
  }

  return context;
};

export const Tooltip = ({
  children,
  ...options
}: { children: React.ReactNode } & TooltipOptions) => {
  // This can accept any props as options, e.g. `placement`,
  // or other positioning options.
  const tooltip = useTooltip(options);
  return <TooltipContext.Provider value={tooltip}>{children}</TooltipContext.Provider>;
};

export const TooltipTrigger = ({
  children,
  ref: propRef,
  asChild = false,
  ...props
}: React.HTMLProps<HTMLElement> & { asChild?: boolean }) => {
  const context = useTooltipContext();
  const ref = useMergeRefs([context.refs.setReference, propRef]);

  // `asChild` allows the user to pass any element as the anchor
  if (asChild && React.isValidElement(children)) {
    return React.cloneElement(
      children,
      context.getReferenceProps({
        ref,
        // biome-ignore lint/suspicious/noExplicitAny: any
        ...(props as any),
        ...(React.isValidElement(children) && typeof children.props === 'object'
          ? children.props
          : {}),
        'data-state': context.open ? 'open' : 'closed',
      }),
    );
  }

  return (
    <button
      ref={ref}
      type='button'
      // The user can style the trigger based on the state
      data-state={context.open ? 'open' : 'closed'}
      {...context.getReferenceProps(props)}
    >
      {children}
    </button>
  );
};

export const TooltipContent = ({
  style,
  ref: propRef,
  ...props
}: React.HTMLProps<HTMLDivElement>) => {
  const context = useTooltipContext();
  const ref = useMergeRefs([context.refs.setFloating, propRef]);

  if (!context.open) return null;
  return (
    <div
      ref={ref}
      style={{
        ...context.floatingStyles,
        ...style,
      }}
      className='z-10 w-max items-center justify-center rounded-4 border border-transparent bg-solid-gray-800 px-2 py-1.5 text-oln-14N-100 text-white'
      {...context.getFloatingProps(props)}
    >
      {props.children}
    </div>
  );
};
