import React, { useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';

interface PasswordInputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  // Any extra props if needed
}

export const PasswordInput: React.FC<PasswordInputProps> = (props) => {
  const [showPassword, setShowPassword] = useState(false);

  // Default styles matching the existing Apcotex theme
  const BORDER = "#E5E7EB";
  const TEAL = "#1FB7B5";

  return (
    <div style={{ position: "relative" }}>
      <input
        {...props}
        type={showPassword ? "text" : "password"}
        style={{
          width: "100%",
          padding: "10px 40px 10px 14px",
          fontSize: "0.875rem",
          border: `1px solid ${BORDER}`,
          borderRadius: 8,
          outline: "none",
          transition: "border-color 0.15s",
          ...props.style,
        }}
        onFocus={(e) => {
          e.currentTarget.style.borderColor = TEAL;
          if (props.onFocus) props.onFocus(e);
        }}
        onBlur={(e) => {
          e.currentTarget.style.borderColor = BORDER;
          if (props.onBlur) props.onBlur(e);
        }}
      />
      <button
        type="button"
        onClick={() => setShowPassword(!showPassword)}
        aria-label={showPassword ? "Hide password" : "Show password"}
        style={{
          position: "absolute",
          right: 10,
          top: "50%",
          transform: "translateY(-50%)",
          background: "none",
          border: "none",
          color: "#9CA3AF",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: 4,
        }}
      >
        {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
      </button>
    </div>
  );
};
