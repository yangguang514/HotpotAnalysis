import { useEffect, useRef, useState } from "react";

interface TokenDialogProps {
  open: boolean;
  onCancel: () => void;
  onSave: (token: string) => void;
}

export function TokenDialog({ open, onCancel, onSave }: TokenDialogProps) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setValue("");
      inputRef.current?.focus();
    }
  }, [open]);

  if (!open) return null;

  return (
    <div className="modal-mask" role="presentation">
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="token-title"
        onKeyDown={(event) => {
          if (event.key === "Escape") onCancel();
          if (event.key === "Enter") onSave(value.trim());
        }}
      >
        <h3 id="token-title">访问令牌</h3>
        <p className="hint">
          该部署设置了访问保护，请输入管理员令牌（ADMIN_TOKEN）。令牌只保存在本浏览器的 localStorage 中。
        </p>
        <input
          ref={inputRef}
          className="input"
          type="password"
          placeholder="ADMIN_TOKEN"
          autoComplete="current-password"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
        <div className="row-end gap">
          <button className="btn btn-ghost" type="button" onClick={onCancel}>取消</button>
          <button className="btn btn-primary" type="button" onClick={() => onSave(value.trim())}>保存</button>
        </div>
      </section>
    </div>
  );
}
