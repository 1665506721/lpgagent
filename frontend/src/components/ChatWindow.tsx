import React, { useState } from "react";

export default function ChatWindow({ messages, onSend }) {
  const [message, setMessage] = useState("");
  const [userId, setUserId] = useState("1");

  const handleSubmit = (event) => {
    event.preventDefault();
    if (!message.trim()) {
      return;
    }
    onSend(message.trim(), userId);
    setMessage("");
  };

  return (
    <div className="chat-window">
      <div className="chat-stream">
        {messages.length === 0 ? (
          <div className="empty-state">
            <h3>开始新的对话</h3>
            <p>发送消息以查看事件链路和最终响应。</p>
          </div>
        ) : null}
        {messages.map((item, index) => (
          <div
            key={`${item.role}-${index}`}
            className={`message-row ${item.role}`}
          >
            <div className="avatar">{item.role === "user" ? "我" : "AI"}</div>
            <div className="bubble">
              {item.content.split("\n").map((line, lineIndex) => (
                <p key={`${index}-${lineIndex}`}>{line}</p>
              ))}
            </div>
          </div>
        ))}
      </div>
      <form className="chat-input" onSubmit={handleSubmit}>
        <input
          className="user-id"
          type="number"
          min="1"
          placeholder="用户ID"
          value={userId}
          onChange={(event) => setUserId(event.target.value)}
        />
        <input
          className="message-input"
          type="text"
          placeholder="输入消息，例如：我要订2瓶15kg送到xx路88号"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
        />
        <button type="submit">发送</button>
      </form>
    </div>
  );
}
