// src/breadmind/web/static/sdui/components/interactive.js
import { useState } from 'preact/hooks';
import { html } from '../renderer.js';

function Button(c, render, ctx) {
  const hasAction = !!c.props.action;
  const buttonType = c.props.submit || !hasAction ? 'submit' : 'button';
  const onClick = (ev) => {
    if (hasAction) {
      ev.preventDefault();
      ctx.dispatch(c.props.action);
    }
    // If no action, let the default submit behavior bubble to the enclosing form.
  };
  const variant = c.props.variant || 'primary';
  return html`<button type=${buttonType} class=${`sdui-button sdui-button--${variant}`} id=${c.id} onClick=${onClick}>${c.props.label || ''}</button>`;
}

function Form(c, render, ctx) {
  // Collect initial field values from descendants
  const initial = {};
  walkFields(c, (f) => {
    if (f.props && f.props.name) {
      initial[f.props.name] = f.props.value || '';
    }
  });
  const [values, setValues] = useState(initial);

  const childCtx = {
    ...ctx,
    formValues: values,
    setFormValue: (name, value) => setValues((v) => ({ ...v, [name]: value })),
  };

  const onSubmit = (ev) => {
    ev.preventDefault();
    if (c.props.action) {
      ctx.dispatch({ ...c.props.action, values });
      // Only reset for chat input and other one-shot composer style forms.
      // Settings forms keep their values so the user can see what was sent
      // and so a second submit click does not blast empties at the server.
      if (c.props.reset_on_submit || c.props.action.kind === 'chat_input') {
        const reset = {};
        Object.keys(initial).forEach(k => { reset[k] = ''; });
        setValues(reset);
      }
    }
  };

  const submitLabel = c.props.submit_label;
  const submitButton = submitLabel
    ? html`<button type="submit" class="sdui-button sdui-button--primary" style="align-self:flex-start;margin-top:4px">${submitLabel}</button>`
    : null;
  return html`<form class="sdui-form" id=${c.id} onSubmit=${onSubmit}>${c.children.map(ch => render(ch, childCtx))}${submitButton}</form>`;
}

function Field(c, render, ctx) {
  const name = c.props.name;
  const val = (ctx.formValues && ctx.formValues[name]) !== undefined
    ? ctx.formValues[name]
    : (c.props.value || '');
  const onInput = (ev) => {
    if (ctx.setFormValue) ctx.setFormValue(name, ev.target.value);
  };
  const onKeyDown = (ev) => {
    // Single-line: Enter submits. Multiline: only when submit_on_enter opt-in
    // (e.g. chat composer). Shift+Enter always inserts a newline in textareas.
    if (ev.key === 'Enter' && !ev.shiftKey && (!c.props.multiline || c.props.submit_on_enter)) {
      ev.preventDefault();
      ev.target.form && ev.target.form.requestSubmit && ev.target.form.requestSubmit();
    }
  };
  const input = c.props.multiline
    ? html`<textarea id=${c.id} name=${name} placeholder=${c.props.placeholder || ''} value=${val} onInput=${onInput} onKeyDown=${onKeyDown} rows="3" />`
    : html`<input id=${c.id} type=${c.props.type || 'text'} name=${name} placeholder=${c.props.placeholder || ''} value=${val} onInput=${onInput} onKeyDown=${onKeyDown} />`;
  return html`<label class="sdui-field">${c.props.label ? html`<span>${c.props.label}</span>` : null}${input}</label>`;
}

function Select(c, render, ctx) {
  const name = c.props.name;
  const val = (ctx.formValues && ctx.formValues[name]) !== undefined
    ? ctx.formValues[name]
    : (c.props.value || '');
  const onChange = (ev) => {
    if (ctx.setFormValue) ctx.setFormValue(name, ev.target.value);
  };
  return html`<label class="sdui-field">${c.props.label ? html`<span>${c.props.label}</span>` : null}
    <select id=${c.id} name=${name} value=${val} onChange=${onChange}>
      ${(c.props.options || []).map(opt => html`<option value=${opt.value}>${opt.label}</option>`)}
    </select>
  </label>`;
}

function Confirm(c, render, ctx) {
  const onYes = () => { if (c.props.yesAction) ctx.dispatch(c.props.yesAction); };
  const onNo = () => { if (c.props.noAction) ctx.dispatch(c.props.noAction); };
  return html`<div class="sdui-confirm" id=${c.id} style="border:1px solid var(--border);padding:16px;border-radius:10px;background:var(--bg-2)">
    <div style="margin-bottom:12px">${c.props.message || ''}</div>
    <div style="display:flex;gap:8px">
      <button type="button" class="sdui-button" onClick=${onYes}>${c.props.yesLabel || '예'}</button>
      <button type="button" class="sdui-button sdui-button--ghost" onClick=${onNo}>${c.props.noLabel || '아니오'}</button>
    </div>
  </div>`;
}

function walkFields(component, cb) {
  if (component.type === 'field' || component.type === 'select') cb(component);
  (component.children || []).forEach(ch => walkFields(ch, cb));
}

export default { button: Button, form: Form, field: Field, select: Select, confirm: Confirm };
