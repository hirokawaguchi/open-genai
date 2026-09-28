export const BLANK_DRAWIO_XML = `<mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="850" pageHeight="1100">
  <root>
    <mxCell id="0"/>
    <mxCell id="1" parent="0"/>
  </root>
</mxGraphModel>`;

export const DRAWIO_FRAME_SRC =
  '/drawio/?embed=1&proto=json&ui=atlas&spin=1&libraries=1&saveAndExit=0&noSaveBtn=1&noExitBtn=1';

export const xmlLooksConverted = (xml: string): boolean =>
  xml.includes('mermaidData') || /vertex=["']1["']/.test(xml);

export const downloadDataUri = (dataUri: string, filename: string) => {
  const link = document.createElement('a');
  link.href = dataUri;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
};

export const safeFileName = (title: string, ext: string) => {
  const base =
    title
      .replace(/[\\/:*?"<>|]+/g, '_')
      .trim()
      .slice(0, 80) || 'diagram';
  return `${base}.${ext}`;
};
