/* 固定离线壳执行的唯一应用脚本；识别内容始终作为数据处理。 */
"use strict";
(() => {
    const root = document.getElementById("document");
    const notice = document.getElementById("notice");
    let parts = [], configuration = {}, serial = 0;
    const mathOptions = {trust: false, strict: "error", throwOnError: true, maxExpand: 256, maxSize: 16};
    const md = window.markdownit({html: true, linkify: true, breaks: false,
        highlight(code, language) {
            if(code.length < 65536 && language && hljs.getLanguage(language)) {
                try { return hljs.highlight(code, {language, ignoreIllegals: true}).value; } catch (_) {}
            }
            return md.utils.escapeHtml(code);
        }
    });
    md.inline.ruler.before("escape", "umi_math", (state, silent) => {
        const start = state.pos, source = state.src;
        let open = "", close = "";
        if(source.startsWith("\\(", start)) { open = "\\("; close = "\\)"; }
        else if(source[start] === "$" && source[start + 1] !== "$" && !/\s/.test(source[start + 1] || " ")) { open = close = "$"; }
        if(!open) return false;
        let end = start + open.length;
        do { end = source.indexOf(close, end); if(end < 0 || end - start > 8192) return false; }
        while(source[end - 1] === "\\" && ++end);
        const value = source.slice(start + open.length, end);
        if(value.includes("\n") || !value.trim()) return false;
        if(!silent) { const token = state.push("umi_math", "span", 0); token.content = value; }
        state.pos = end + close.length;
        return true;
    });
    md.block.ruler.before("fence", "umi_math_block", (state, startLine, endLine, silent) => {
        const start = state.bMarks[startLine] + state.tShift[startLine];
        const first = state.src.slice(start, state.eMarks[startLine]).trim();
        const open = first.startsWith("$$") ? "$$" : first.startsWith("\\[") ? "\\[" : "";
        if(!open) return false;
        const close = open === "$$" ? "$$" : "\\]";
        let line = startLine, end = state.src.indexOf(close, start + open.length);
        if(end < 0 || end - start > 65536) return false;
        while(line < endLine && state.eMarks[line] < end + close.length) line++;
        if(line >= endLine || state.src.slice(end + close.length, state.eMarks[line]).trim()) return false;
        if(silent) return true;
        const token = state.push("umi_math_block", "div", 0);
        token.content = state.src.slice(start + open.length, end).trim();
        token.block = true;
        token.map = [startLine, line + 1];
        state.line = line + 1;
        return true;
    });
    const mathToken = (tokens, index) => '<span class="umi-math' + (tokens[index].block ? ' umi-display' : '')
        + '">' + md.utils.escapeHtml(tokens[index].content) + "</span>";
    md.renderer.rules.umi_math = mathToken;
    md.renderer.rules.umi_math_block = mathToken;

    DOMPurify.addHook("uponSanitizeAttribute", (node, attribute) => {
        if(attribute.attrName === "src") {
            let value = configuration.assets[attribute.attrValue];
            if(!value) { try { value = configuration.assets[decodeURI(attribute.attrValue)]; } catch (_) {} }
            if(node.tagName !== "IMG" || !value) attribute.keepAttr = false;
            else attribute.attrValue = value;
        } else if(attribute.attrName === "href") {
            if(node.tagName !== "A" || !/^(?:https?:\/\/|#[^\s]*)/i.test(attribute.attrValue)) attribute.keepAttr = false;
        }
    });
    const sanitize = html => DOMPurify.sanitize(html, {
        RETURN_DOM_FRAGMENT: true,
        ALLOWED_TAGS: ["p", "div", "span", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "table", "thead", "tbody", "tfoot", "tr", "td", "th", "blockquote", "pre", "code", "strong", "em", "b", "i", "s", "del", "sup", "sub", "br", "hr", "a", "img", "dl", "dt", "dd"],
        ALLOWED_ATTR: ["class", "href", "src", "alt", "title", "colspan", "rowspan", "align", "start"],
        ALLOW_DATA_ATTR: false,
        ALLOWED_URI_REGEXP: /^(?:https?:|#|umi-preview:\/\/reader\/assets\/)/i
    });
    function typeset(container) {
        for(const element of container.querySelectorAll(".umi-math")) {
            const tex = element.textContent;
            try {
                if(tex.length > 65536) throw new Error("formula budget");
                katex.render(tex, element, {...mathOptions, displayMode: element.classList.contains("umi-display")});
            }
            catch (error) { element.textContent = tex; element.classList.add("katex-error"); element.title = String(error.message || error); }
        }
        renderMathInElement(container, {...mathOptions, delimiters: [
            {left: "$$", right: "$$", display: true}, {left: "\\[", right: "\\]", display: true},
            {left: "\\(", right: "\\)", display: false}, {left: "$", right: "$", display: false}
        ], ignoredClasses: ["umi-math", "katex"], errorCallback() {}});
        for(const table of container.querySelectorAll("table")) {
            const wrapper = document.createElement("div"); wrapper.className = "table-scroll";
            table.before(wrapper); wrapper.append(table);
        }
        for(const pre of container.querySelectorAll("pre")) {
            const code = pre.querySelector("code"); if(!code) continue;
            const count = code.textContent.replace(/\n$/, "").split("\n").length;
            if(count > 1 && count <= 2000) {
                const lines = document.createElement("span"); lines.className = "code-lines";
                lines.setAttribute("aria-hidden", "true");
                lines.textContent = Array.from({length: count}, (_, index) => index + 1).join("\n");
                pre.classList.add("numbered"); pre.prepend(lines);
            }
        }
    }
    function segments(source) {
        const result = []; let buffer = [], size = 0, fence = "", math = false, divs = 0;
        for(const line of source.split("\n")) {
            const marker = /^\s*(`{3,}|~{3,})/.exec(line);
            if(marker) { if(!fence) fence = marker[1]; else if(marker[1][0] === fence[0] && marker[1].length >= fence.length) fence = ""; }
            if(!fence) {
                if(/^\s*(?:\$\$|\\\[)\s*$/.test(line)) math = !math;
                if(/^\s*\\\]\s*$/.test(line)) math = false;
                divs += (line.match(/<div\b/gi) || []).length - (line.match(/<\/div\s*>/gi) || []).length;
            }
            buffer.push(line); size += line.length + 1;
            if(size >= 32768 && !line.trim() && !fence && !math && divs <= 0) {
                result.push(buffer.join("\n")); buffer = []; size = 0;
            }
        }
        if(buffer.length) result.push(buffer.join("\n"));
        return result;
    }
    function theme(presentation) {
        configuration.presentation = presentation || {};
        const p = configuration.presentation, style = document.documentElement.style;
        for(const [key, value] of Object.entries({paper: p.background, ink: p.foreground, muted: p.muted, link: p.link, rule: p.border}))
            if(value) style.setProperty("--" + key, value);
        if(p.font) style.setProperty("--font", JSON.stringify(p.font) + ", sans-serif");
        if(p.fontSize > 0) style.setProperty("--size", Math.max(10, p.fontSize) + "px");
        document.documentElement.dataset.dark = p.dark ? "true" : "false";
        document.getElementById("highlight-light").disabled = !!p.dark;
        document.getElementById("highlight-dark").disabled = !p.dark;
    }
    window.umiPreview = {
        ready: true, rendered: false, revision: 0,
        clear() { serial++; parts = []; root.replaceChildren(); notice.hidden = true; this.rendered = false; return true; },
        begin(config) { this.clear(); configuration = config; configuration.assets = config.assets || {}; this.revision = config.revision; theme(config.presentation); return true; },
        append(text) { parts.push(text); return true; },
        theme,
        finish() {
            const source = parts.join(""); parts = []; const current = serial;
            const chunks = segments(source); let index = 0;
            const next = () => {
                if(current !== serial) return;
                if(index >= chunks.length) {
                    if(!source.trim()) { const empty = document.createElement("p"); empty.className = "empty"; empty.textContent = configuration.presentation.empty || ""; root.append(empty); }
                    notice.textContent = configuration.deniedAssets ? configuration.presentation.blocked || "" : "";
                    notice.hidden = !notice.textContent; this.rendered = true; return;
                }
                const part = chunks[index++], section = document.createElement("section"); section.className = "document-section";
                try {
                    if(part.length > 262144) {
                        const hint = document.createElement("p"), pre = document.createElement("pre");
                        hint.className = "empty"; hint.textContent = configuration.presentation.longBlock || "";
                        pre.textContent = part; section.append(hint, pre);
                    } else { section.append(sanitize(md.render(part))); typeset(section); }
                } catch (_) { const pre = document.createElement("pre"); pre.textContent = part; section.append(pre); }
                root.append(section); setTimeout(next, 0);
            };
            next(); return true;
        }
    };
    document.addEventListener("click", event => {
        const link = event.target.closest("a");
        if(link && link.getAttribute("href")?.startsWith("#")) {
            event.preventDefault(); document.getElementById(link.getAttribute("href").slice(1))?.scrollIntoView();
        }
    });
})();
