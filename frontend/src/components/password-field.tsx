"use client";

import { useState, type ComponentProps } from "react";
import { Icon } from "@/components/icons";
import { useI18n } from "@/i18n/provider";

type PasswordFieldProps = Omit<ComponentProps<"input">, "type" | "id"> & {
  id: string;
  label: string;
};

export function PasswordField({ id, label, disabled, ...inputProps }: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);
  const { t } = useI18n();
  const action = t(visible ? "Hide password" : "Show password");

  return <div className="password-field">
    <label htmlFor={id}>{label}</label>
    <div className="password-input">
      <input {...inputProps} id={id} type={visible ? "text" : "password"} disabled={disabled} spellCheck={false} autoCapitalize="none" autoCorrect="off" />
      <button type="button" className="icon-button password-visibility" disabled={disabled}
        aria-label={action} title={action} aria-controls={id}
        onPointerDown={event => event.preventDefault()}
        onClick={() => setVisible(current => !current)}>
        <Icon name={visible ? "eye-off" : "eye"} />
      </button>
    </div>
  </div>;
}
