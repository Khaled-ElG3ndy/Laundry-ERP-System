const {
  AlignmentType, BorderStyle, HeadingLevel, LevelFormat, Paragraph, ShadingType,
  Table, TableCell, TableRow, TextRun, WidthType, convertInchesToTwip,
} = require('docx');

const FONT = { ascii: 'Arial', hAnsi: 'Arial', cs: 'Arial' };
const CONTENT_WIDTH = 9026;           // A4 minus 1" margins, in DXA
const NAVY = '1B3A6B';
const TEAL = '0F6E6E';
const GREY = 'F2F4F7';
const BAND = 'E8EEF7';

/** A run of Arabic text. */
const run = (text, options = {}) => new TextRun({
  text,
  rightToLeft: true,
  font: FONT,
  ...options,
});

/** A right-to-left paragraph. */
const para = (text, options = {}) => {
  const { bold, color, size, spacingBefore = 0, spacingAfter = 120,
          alignment = AlignmentType.RIGHT, indent, runs } = options;
  return new Paragraph({
    bidirectional: true,
    alignment,
    indent,
    spacing: { before: spacingBefore, after: spacingAfter, line: 300 },
    children: runs || [run(text, { bold, color, size: size || 22 })],
  });
};

const heading = (text, level = HeadingLevel.HEADING_1, options = {}) => new Paragraph({
  bidirectional: true,
  alignment: AlignmentType.RIGHT,
  heading: level,
  pageBreakBefore: options.pageBreakBefore || false,
  spacing: {
    before: options.pageBreakBefore
      ? 0
      : (level === HeadingLevel.HEADING_1 ? 360 : 260),
    after: 140,
  },
  children: [run(text, {
    bold: true,
    color: level === HeadingLevel.HEADING_1 ? NAVY : TEAL,
    size: level === HeadingLevel.HEADING_1 ? 30 : 25,
  })],
});

/** A bulleted line. */
const bullet = (text, options = {}) => new Paragraph({
  bidirectional: true,
  alignment: AlignmentType.RIGHT,
  numbering: { reference: 'dots', level: options.level || 0 },
  spacing: { after: 80, line: 290 },
  children: options.runs || [run(text, { size: 22 })],
});

/** A numbered step. */
const step = (text, options = {}) => new Paragraph({
  bidirectional: true,
  alignment: AlignmentType.RIGHT,
  numbering: { reference: options.reference, level: 0 },
  spacing: { after: 80, line: 290 },
  children: options.runs || [run(text, { size: 22 })],
});

const cell = (text, options = {}) => {
  const { width, bold, fill, size = 21, alignment = AlignmentType.RIGHT,
           runs } = options;
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: fill ? { type: ShadingType.CLEAR, fill, color: 'auto' } : undefined,
    margins: { top: 90, bottom: 90, left: 120, right: 120 },
    children: [new Paragraph({
      bidirectional: true,
      alignment,
      spacing: { after: 0, line: 280 },
      children: runs || [run(text, { bold, size,
                                     color: bold && fill === NAVY ? 'FFFFFF' : undefined })],
    })],
  });
};

/** A table whose header is the first row of `rows`. */
const table = (columnWidths, rows, options = {}) => {
  const { headerFill = NAVY, zebra = true } = options;
  return new Table({
    width: { size: columnWidths.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    columnWidths,
    visuallyRightToLeft: true,
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: 'C6CEDB' },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: 'C6CEDB' },
      left: { style: BorderStyle.SINGLE, size: 4, color: 'C6CEDB' },
      right: { style: BorderStyle.SINGLE, size: 4, color: 'C6CEDB' },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 3, color: 'D9DFE8' },
      insideVertical: { style: BorderStyle.SINGLE, size: 3, color: 'D9DFE8' },
    },
    rows: rows.map((cells, rowIndex) => new TableRow({
      tableHeader: rowIndex === 0,
      children: cells.map((text, columnIndex) => cell(text, {
        width: columnWidths[columnIndex],
        bold: rowIndex === 0,
        fill: rowIndex === 0
          ? headerFill
          : (zebra && rowIndex % 2 === 0 ? GREY : undefined),
      })),
    })),
  });
};

/** A tinted box for a note or a warning. */
const callout = (title, lines, fill = BAND, accent = NAVY) => new Table({
  width: { size: CONTENT_WIDTH, type: WidthType.DXA },
  columnWidths: [CONTENT_WIDTH],
  visuallyRightToLeft: true,
  borders: {
    top: { style: BorderStyle.SINGLE, size: 4, color: accent },
    bottom: { style: BorderStyle.SINGLE, size: 4, color: accent },
    left: { style: BorderStyle.SINGLE, size: 4, color: accent },
    right: { style: BorderStyle.SINGLE, size: 12, color: accent },
    insideHorizontal: { style: BorderStyle.NONE, size: 0, color: 'auto' },
    insideVertical: { style: BorderStyle.NONE, size: 0, color: 'auto' },
  },
  rows: [new TableRow({
    children: [new TableCell({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      shading: { type: ShadingType.CLEAR, fill, color: 'auto' },
      margins: { top: 140, bottom: 140, left: 160, right: 160 },
      children: [
        new Paragraph({
          bidirectional: true,
          alignment: AlignmentType.RIGHT,
          spacing: { after: lines.length ? 100 : 0, line: 280 },
          children: [run(title, { bold: true, color: accent, size: 23 })],
        }),
        ...lines.map((line, index) => new Paragraph({
          bidirectional: true,
          alignment: AlignmentType.RIGHT,
          spacing: { after: index === lines.length - 1 ? 0 : 80, line: 285 },
          children: [run(line, { size: 21 })],
        })),
      ],
    })],
  })],
});

const spacer = (size = 120) => new Paragraph({ spacing: { after: size }, children: [] });

const rule = () => new Paragraph({
  spacing: { before: 60, after: 160 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: 'C6CEDB' } },
  children: [],
});

const numbering = {
  config: [
    {
      reference: 'dots',
      levels: [
        { level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.RIGHT,
          style: { paragraph: { indent: { right: convertInchesToTwip(0.28), hanging: convertInchesToTwip(0.2) } } } },
        { level: 1, format: LevelFormat.BULLET, text: '–', alignment: AlignmentType.RIGHT,
          style: { paragraph: { indent: { right: convertInchesToTwip(0.56), hanging: convertInchesToTwip(0.2) } } } },
      ],
    },
    ...['t0', 't1', 't2', 't3', 't4', 't5', 't6', 't7', 't8', 'rec'].map((reference) => ({
      reference,
      levels: [{
        level: 0,
        format: LevelFormat.DECIMAL,
        text: '%1.',
        alignment: AlignmentType.RIGHT,
        style: { paragraph: { indent: { right: convertInchesToTwip(0.3), hanging: convertInchesToTwip(0.22) } } },
      }],
    })),
  ],
};

module.exports = { AlignmentType, CONTENT_WIDTH, FONT, HeadingLevel, NAVY, TEAL,
                   BAND, GREY, bullet, callout, cell, heading, numbering, para,
                   rule, run, spacer, step, table };
