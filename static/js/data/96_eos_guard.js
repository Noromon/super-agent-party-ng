// S160 潜龙勿用：EOS 污染防御与存量隔离面板的状态域默认值。
// eosGuardSettings 经 settings_schema PAIRS 持久化（wire 键 eosGuard）；
// eosPatrol 仅为面板工作态，不落盘。
Object.assign(vue_data, {
    eosGuardSettings: {
        enabled: false,
        sanitize: true,
        softBias: -30,
        eosTokenIds: [248044, 248046]
    },
    eosPatrol: {
        scanning: false,
        applying: false,
        restoring: false,
        report: null,
        showReportOnly: false,
        confirmToken: '',
        sanitizeActive: true,
        idsText: '248044, 248046',
        backups: [],
        quarantineFiles: []
    }
});
