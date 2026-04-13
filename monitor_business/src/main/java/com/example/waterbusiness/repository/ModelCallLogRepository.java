package com.example.waterbusiness.repository;

import com.example.waterbusiness.entity.ModelCallLog;
import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDateTime;
import java.util.List;

public interface ModelCallLogRepository extends JpaRepository<ModelCallLog, Long> {

    List<ModelCallLog> findByCreatedAtGreaterThanEqualAndCreatedAtLessThanAndSuccessIsFalse(
            LocalDateTime from,
            LocalDateTime toExclusive
    );

    long countBySuccessIsFalse();

    long countByCreatedAtGreaterThanEqualAndCreatedAtLessThanAndSuccessIsFalse(
            LocalDateTime from,
            LocalDateTime toExclusive
    );
}
