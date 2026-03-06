import { useEffect, useMemo, useState } from "react";
import type { FormPayload } from "../../lib/api";
import { buildFields, normalizePayload, resolvePlaceholder } from "../../lib/schemaForm";

type PortalFormModalProps = {
  open: boolean;
  form: FormPayload | null;
  onClose: () => void;
  onSubmit: (formId: string, payload: Record<string, unknown>) => Promise<void>;
};

export default function PortalFormModal({
  open,
  form,
  onClose,
  onSubmit
}: PortalFormModalProps) {
  const fields = useMemo(() => buildFields(form?.schema), [form]);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setValues(form?.prefill || {});
    setErrors({});
  }, [form]);

  if (!open || !form) {
    return null;
  }

  const handleSubmit = async () => {
    const requiredErrors: Record<string, string> = {};
    fields.forEach((field) => {
      if (field.required && (values[field.name] === undefined || values[field.name] === "")) {
        requiredErrors[field.name] = "必填项";
      }
    });
    setErrors(requiredErrors);
    if (Object.keys(requiredErrors).length > 0) {
      return;
    }
    setSubmitting(true);
    try {
      await onSubmit(form.form_id, normalizePayload(fields, values));
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="portal-modal">
      <div className="portal-modal-card wide">
        <div className="portal-modal-header">
          <div>
            <h3>{form.title}</h3>
            <p>{form.description}</p>
          </div>
          <button className="portal-ghost" type="button" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="portal-form-grid">
          {fields.map((field) => (
            <label key={field.name} className={field.name === "notes" ? "portal-form-full" : ""}>
              <span>
                {field.label}
                {field.required ? " *" : ""}
              </span>
              {field.type === "enum" ? (
                <select
                  value={String(values[field.name] ?? "")}
                  onChange={(event) =>
                    setValues((prev) => ({ ...prev, [field.name]: event.target.value }))
                  }
                >
                  <option value="">请选择</option>
                  {field.options?.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              ) : field.type === "boolean" ? (
                <input
                  type="checkbox"
                  checked={Boolean(values[field.name])}
                  onChange={(event) =>
                    setValues((prev) => ({ ...prev, [field.name]: event.target.checked }))
                  }
                />
              ) : field.name === "notes" ? (
                <textarea
                  rows={3}
                  value={String(values[field.name] ?? "")}
                  placeholder={resolvePlaceholder(field.name)}
                  onChange={(event) =>
                    setValues((prev) => ({ ...prev, [field.name]: event.target.value }))
                  }
                />
              ) : (
                <input
                  value={String(values[field.name] ?? "")}
                  placeholder={resolvePlaceholder(field.name)}
                  onChange={(event) =>
                    setValues((prev) => ({ ...prev, [field.name]: event.target.value }))
                  }
                />
              )}
              {errors[field.name] ? <small>{errors[field.name]}</small> : null}
            </label>
          ))}
        </div>
        <div className="portal-actions">
          <button className="portal-secondary" type="button" onClick={onClose}>
            取消
          </button>
          <button className="portal-cta" type="button" onClick={handleSubmit} disabled={submitting}>
            {submitting ? "提交中..." : form.cta_label || "提交"}
          </button>
        </div>
      </div>
    </div>
  );
}
