package com.example.waterbusiness.repository;

import com.example.waterbusiness.entity.ModelCallLog;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

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

    @Query("""
            select m from ModelCallLog m
            join WaterQualityRecord r on r.id = m.waterQualityRecordId
            where r.stationId = :stationId
              and m.createdAt >= :from
              and m.createdAt < :toExclusive
              and m.success = false
            """)
    List<ModelCallLog> findFailuresByStationIdAndCreatedAtRange(
            @Param("stationId") Long stationId,
            @Param("from") LocalDateTime from,
            @Param("toExclusive") LocalDateTime toExclusive
    );
}
