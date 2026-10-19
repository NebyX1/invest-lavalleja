type Block =
  | { type: 'heading'; text: string }
  | { type: 'paragraph'; text: string }
  | { type: 'unordered' | 'ordered'; items: string[] };

function plain(value: string) {
  return value.replace(/\*\*([^*]+)\*\*/g, '$1').replace(/__([^_]+)__/g, '$1').trim();
}

function parseAnswer(value: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: Extract<Block, { type: 'unordered' | 'ordered' }> | null = null;
  const flushParagraph = () => {
    if (paragraph.length) blocks.push({ type: 'paragraph', text: plain(paragraph.join('\n')) });
    paragraph = [];
  };
  const flushList = () => {
    if (list?.items.length) blocks.push(list);
    list = null;
  };

  for (const raw of value.replace(/\r/g, '').split('\n')) {
    const line = raw.trim();
    if (!line) { flushParagraph(); flushList(); continue; }
    const heading = line.match(/^#{1,4}\s+(.+)$/);
    const unordered = line.match(/^[-*]\s+(.+)$/);
    const ordered = line.match(/^\d+[.)]\s+(.+)$/);
    if (heading) { flushParagraph(); flushList(); blocks.push({ type: 'heading', text: plain(heading[1]) }); continue; }
    if (unordered || ordered) {
      flushParagraph();
      const type = unordered ? 'unordered' : 'ordered';
      if (list && list.type !== type) flushList();
      list ??= { type, items: [] };
      list.items.push(plain((unordered ?? ordered)![1]));
      continue;
    }
    flushList(); paragraph.push(line);
  }
  flushParagraph(); flushList();
  return blocks;
}

export default function AnswerContent({ text }: { text: string }) {
  return <div className="gianna-answer-text">
    {parseAnswer(text).map((block, index) => {
      if (block.type === 'heading') return <h4 key={index}>{block.text}</h4>;
      if (block.type === 'paragraph') return <p key={index}>{block.text}</p>;
      const Tag = block.type === 'ordered' ? 'ol' : 'ul';
      return <Tag key={index}>{block.items.map((item, itemIndex) => <li key={itemIndex}>{item}</li>)}</Tag>;
    })}
  </div>;
}
