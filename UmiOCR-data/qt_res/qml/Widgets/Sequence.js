.pragma library

// Python QVariantList／Repeater 的序列不一定满足 Array.isArray。
function isSequence(value) {
    return value !== null && value !== undefined && typeof value === "object"
        && typeof value.length === "number" && Number.isFinite(value.length) && value.length >= 0
        && Math.floor(value.length) === value.length
}

function warnings(value) {
    const result = []
    function append(item) {
        if(item === null || item === undefined) return
        if(isSequence(item)) {
            for(let i = 0; i < item.length; ++i) append(item[i])
            return
        }
        if(typeof item === "object" && Object.keys(item).length === 0) return
        const text = String(typeof item === "object"
            ? (item.message || JSON.stringify(item)) : item).trim()
        if(text && result.indexOf(text) < 0) result.push(text)
    }
    append(value)
    return result
}
