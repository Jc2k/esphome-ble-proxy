from esphome import codegen as cg
import esphome.config_validation as cv
from esphome.const import CONF_ID


DEPENDENCIES = ["esp32"]

partition_diagnostics_ns = cg.esphome_ns.namespace("partition_diagnostics")
PartitionDiagnosticsComponent = partition_diagnostics_ns.class_(
    "PartitionDiagnosticsComponent", cg.Component
)

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(PartitionDiagnosticsComponent),
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
