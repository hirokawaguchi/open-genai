type Props = {
  title: string;
};

export const Title = (props: Props) => {
  const { title } = props;

  return (
    <h1 className='min-w-0 text-std-16B-170 text-pretty print:visible print:my-5 print:text-std-24B-150'>
      {title}
    </h1>
  );
};
