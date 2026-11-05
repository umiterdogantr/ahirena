import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Model çıktısı güvenilmeyen içeriktir: bağlantılar uygulama penceresini başka
 * adrese götürmesin ve uzak görseller sessizce ağ isteği yapmasın diye ikisi de
 * düz metin olarak gösterilir.
 */
export default function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ children, href }) => (
            <span className="md-link" title={href}>
              {children}
            </span>
          ),
          img: ({ alt, src }) => <span className="muted">[görsel: {alt || src}]</span>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
