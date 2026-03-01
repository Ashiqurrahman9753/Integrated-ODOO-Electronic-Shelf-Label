/** @odoo-module **/
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { ListController } from "@web/views/list/list_controller";
import { onMounted } from "@odoo/owl";

patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);

        if (this.props.resModel !== "sunlux.esl.tag") {
            return;
        }

        const busService = useService("bus_service");

        busService.subscribe("sunlux_esl_refresh", () => {
            if (this.__owl__ && this.__owl__.status !== 5) {
                this.model.load();
            }
        });

        onMounted(() => {
            busService.start();
        });
    },
});
