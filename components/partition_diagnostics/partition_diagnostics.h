#pragma once

#include "esphome/core/component.h"

#include <esp_partition.h>

namespace esphome::partition_diagnostics {

class PartitionDiagnosticsComponent : public Component {
 public:
  void setup() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::HARDWARE; }

 protected:
  bool check_partition_(const esp_partition_t *partition, uint32_t address, size_t size) const;
  bool check_nvs_ota_compatible_(const esp_partition_t *partition) const;

  const esp_partition_t *running_partition_{nullptr};
  const esp_partition_t *otadata_partition_{nullptr};
  const esp_partition_t *phy_partition_{nullptr};
  const esp_partition_t *app0_partition_{nullptr};
  const esp_partition_t *app1_partition_{nullptr};
  const esp_partition_t *nvs_partition_{nullptr};
  uint32_t flash_size_{0};
  bool target_layout_matches_{false};
  bool ota_layout_compatible_{false};
};

}  // namespace esphome::partition_diagnostics
