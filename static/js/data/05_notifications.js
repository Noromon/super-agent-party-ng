// S151：通知中心状态域（Object.assign 装配，加载顺序在宿主之后、renderer 之前）。
Object.assign(vue_data, {
    notificationsOpen: false,

    notificationItems: [],

    notificationFilter: '',

    notifLoading: false,
});
