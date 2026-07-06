package com.example.waterbusiness.repository;

import com.example.waterbusiness.entity.AsyncTask;
import com.example.waterbusiness.entity.AsyncTaskStatus;
import com.example.waterbusiness.entity.AsyncTaskType;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import jakarta.persistence.LockModeType;
import org.springframework.data.domain.Pageable;

import java.util.List;
import java.time.LocalDateTime;

import java.util.Optional;

public interface AsyncTaskRepository extends JpaRepository<AsyncTask, Long> {
    Optional<AsyncTask> findByTaskId(String taskId);

    Optional<AsyncTask> findByTaskTypeAndIdempotencyKey(AsyncTaskType taskType, String idempotencyKey);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("""
            select t
            from AsyncTask t
            where t.taskType = :taskType
              and t.status in :statuses
            order by t.createdAt desc
            """)
    List<AsyncTask> findInFlightTasksForUpdate(
            @Param("taskType") AsyncTaskType taskType,
            @Param("statuses") List<AsyncTaskStatus> statuses,
            Pageable pageable
    );

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("""
            delete from AsyncTask t
            where t.createdAt < :cutoff
              and t.status in :statuses
            """)
    int deleteByCreatedAtBeforeAndStatusIn(
            @Param("cutoff") LocalDateTime cutoff,
            @Param("statuses") List<AsyncTaskStatus> statuses
    );
}
