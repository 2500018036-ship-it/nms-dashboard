let preferences = { timezone:'Asia/Jakarta', date_format:'id-ID' }
export function setDisplayPreferences(value) { if (value?.timezone && value?.date_format) preferences = { timezone:value.timezone, date_format:value.date_format } }
export function displayPreferences() { return preferences }
