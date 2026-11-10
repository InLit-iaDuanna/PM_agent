import { ChatSessionLivePage } from "../../../features/research/components/chat-session-live-page";

export default async function ChatSessionPage({ params }: { params: Promise<{ sessionId: string }> }) {
  return <ChatSessionLivePage sessionId={(await params).sessionId} />;
}
